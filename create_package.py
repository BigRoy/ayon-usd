"""Prepares server package from addon repo to upload to server.

Requires Python 3.9. (Or at least 3.8+).

This script should be called from cloned addon repo.

It will produce 'package' subdirectory which could be pasted into server
addon directory directly (e.g. into `ayon-backend/addons`).

Format of package folder:
ADDON_REPO/package/{addon name}/{addon version}

You can specify `--output_dir` in arguments to change output directory where
package will be created. Existing package directory will always be purged if
already present! This could be used to create package directly in server folder
if available.

Package contains server side files directly,
client side code zipped in `private` subfolder.
"""

import argparse
import collections
import contextlib
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional
import package

ADDON_NAME: str = package.name
ADDON_VERSION: str = package.version
ADDON_CLIENT_DIR: str = package.client_dir


CLIENT_VERSION_CONTENT = '''# -*- coding: utf-8 -*-
"""Package declaring ayon_usd addon version.

Version is regenerated by `create_package.py` script or the
build system based on the content of package.py.

Do not manually edit this file.
"""
name = "{}"
__version__ = "{}"
'''

# Set sources to download
AYON_SOURCE_URL = "https://distribute.openpype.io/thirdparty"
USD_SOURCES = {
        "24.03": {
            "windows": {
                "url": f"{AYON_SOURCE_URL}/usd-24.03_win64_py39.zip",
                "checksum": "7d7852b9c8e3501e5f64175decc08d70e3bf1c083faaaf2c1a8aa8f9af43ab30",
                "checksum_algorithm": "sha256",
            },
            "linux": {
                "url": f"{AYON_SOURCE_URL}/usd-24.03_linux_py39.zip",
                "checksum": "27010ad67d5acd25e3c95b1ace4ab30e047b5a9e48082db0545ae44ae7ec9b09",
                "checksum_algorithm": "sha256",
            }
        }
    }

# Patterns of directories to be skipped for server part of addon
IGNORE_DIR_PATTERNS = [
    re.compile(pattern)
    for pattern in {
        # Skip directories starting with '.'
        r"^\.",
        # Skip any pycache folders
        "^__pycache__$"
    }
]

# Patterns of files to be skipped for server part of addon
IGNORE_FILE_PATTERNS = [
    re.compile(pattern)
    for pattern in {
        # Skip files starting with '.'
        # NOTE this could be an issue in some cases
        r"^\.",
        # Skip '.pyc' files
        r"\.pyc$"
    }
]


def calculate_file_checksum(
        filepath, hash_algorithm, chunk_size=10000):
    """Calculate file checksum.

    Args:
        filepath (str): File path.
        hash_algorithm (str): Hash algorithm.
        chunk_size (int, optional): Chunk size for reading file.

    Returns:
        str: Checksum of file.

    """
    func = getattr(hashlib, hash_algorithm)
    hash_obj = func()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            hash_obj.update(chunk)
    return hash_obj.hexdigest()


class ZipFileLongPaths(zipfile.ZipFile):
    r"""Allows longer paths in zip files.

    Regular DOS paths are limited to MAX_PATH (260) characters, including
    the string's terminating NUL character.
    That limit can be exceeded by using an extended-length path that
    starts with the '\\?\' prefix.
    """

    _is_windows = platform.system().lower() == "windows"

    def _extract_member(self, member, tpath, pwd):
        if self._is_windows:
            tpath = os.path.abspath(tpath)
            if tpath.startswith("\\\\"):
                tpath = "\\\\?\\UNC\\" + tpath[2:]
            else:
                tpath = "\\\\?\\" + tpath

        return super(ZipFileLongPaths, self)._extract_member(
            member, tpath, pwd
        )


def safe_copy_file(src_path, dst_path):
    """Copy file and make sure destination directory exists.

    Ignore if destination already contains directories from source.

    Args:
        src_path (str): File path that will be copied.
        dst_path (str): Path to destination file.

    """
    if src_path == dst_path:
        return

    dst_dir = os.path.dirname(dst_path)
    with contextlib.suppress(Exception):
        os.makedirs(dst_dir)
    shutil.copy2(src_path, dst_path)


def _value_match_regexes(value, regexes):
    return any(regex.search(value) for regex in regexes)


def find_files_in_subdir(
    src_path,
    ignore_file_patterns=None,
    ignore_dir_patterns=None
):
    """Find files in subdirectories.

    Args:
        src_path (str): Source directory path.
        ignore_file_patterns (list, optional): List of regex patterns
            to ignore files.
        ignore_dir_patterns (list, optional): List of regex patterns
            to ignore directories.

    Returns:
        list: List of tuples with file path and relative path.

    """
    if ignore_file_patterns is None:
        ignore_file_patterns = IGNORE_FILE_PATTERNS

    if ignore_dir_patterns is None:
        ignore_dir_patterns = IGNORE_DIR_PATTERNS
    output = []

    hierarchy_queue = collections.deque()
    hierarchy_queue.append((src_path, []))
    while hierarchy_queue:
        item = hierarchy_queue.popleft()
        dirpath, parents = item
        for name in os.listdir(dirpath):
            path = os.path.join(dirpath, name)
            if os.path.isfile(path):
                if not _value_match_regexes(name, ignore_file_patterns):
                    items = list(parents)
                    items.append(name)
                    output.append((path, os.path.sep.join(items)))
                continue

            if not _value_match_regexes(name, ignore_dir_patterns):
                items = list(parents)
                items.append(name)
                hierarchy_queue.append((path, items))

    return output


def copy_server_content(addon_output_dir, current_dir, log):
    """Copy server side folders to 'addon_package_dir'.

    Args:
        addon_output_dir (str): package dir in addon repo dir
        current_dir (str): addon repo dir
        log (logging.Logger)

    """
    log.info("Copying server content")

    filepaths_to_copy = []
    server_dirpath = os.path.join(current_dir, "server")

    for item in find_files_in_subdir(server_dirpath):
        src_path, dst_subpath = item
        dst_path = os.path.join(addon_output_dir, "server", dst_subpath)
        filepaths_to_copy.append((src_path, dst_path))

    # Copy files
    for src_path, dst_path in filepaths_to_copy:
        safe_copy_file(src_path, dst_path)


def _fill_client_version(current_dir):
    version_file = os.path.join(
        current_dir, "client", ADDON_CLIENT_DIR, "version.py"
    )
    with open(version_file, "w") as stream:
        stream.write(
            CLIENT_VERSION_CONTENT.format(
                ADDON_NAME, ADDON_VERSION))


def zip_client_side(addon_package_dir, current_dir, log):
    """Copy and zip `client` content into 'addon_package_dir'.

    Args:
        addon_package_dir (str): Output package directory path.
        current_dir (str): Directory path of addon source.
        log (logging.Logger): Logger object.

    """
    client_dir = os.path.join(current_dir, "client")
    if not os.path.isdir(client_dir):
        log.info("Client directory was not found. Skipping")
        return

    log.info("Preparing client code zip")
    private_dir = os.path.join(addon_package_dir, "private")

    if not os.path.exists(private_dir):
        os.makedirs(private_dir)

    zip_filepath = os.path.join(os.path.join(private_dir, "client.zip"))
    with ZipFileLongPaths(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Add client code content to zip
        for path, sub_path in find_files_in_subdir(client_dir):
            zipf.write(path, sub_path)


def download_usd_zip(downloads_dir: Path, log: logging.Logger):
    """Download USD zip files.

    Args:
        downloads_dir (Path): Directory path to download zip files.
        log (logging.Logger): Logger object.

    """
    zip_files_info = []
    for item_name, item_info in USD_SOURCES.items():
        for platform_name, platform_info in item_info.items():
            src_url = platform_info["url"]
            filename = src_url.split("/")[-1]
            zip_path = downloads_dir / filename
            checksum = platform_info["checksum"]
            checksum_algorithm = platform_info["checksum_algorithm"]
            zip_files_info.append({
                "name": ADDON_NAME,
                "filename": filename,
                "checksum": checksum,
                "checksum_algorithm": checksum_algorithm,
                "platform": platform_name,
            })
            if zip_path.exists():
                file_checksum = calculate_file_checksum(
                    zip_path, checksum_algorithm)
                if checksum == file_checksum:
                    log.debug(f"USD zip from {src_url} already exists")
                    continue
                os.remove(zip_path)

            log.debug(f"USD zip from {src_url} -> {zip_path}")
            log.info("USD zip download - started")

            urllib.request.urlretrieve(
                src_url,
                zip_path)
            log.info("USD zip download - finished")

            file_checksum = calculate_file_checksum(
                zip_path, checksum_algorithm)

            if checksum != file_checksum:
                raise ValueError(
                    f"USD zip checksum mismatch: {file_checksum} != {checksum}"
                )

    return zip_files_info


def create_server_package(
    current_dir: str,
    output_dir: str,
    addon_output_dir: str,
    addon_version: str,
    log: logging.Logger
):
    """Create server package zip file.

    The zip file can be installed to a server using UI or rest api endpoints.

    Args:
        current_dir (str): Directory path of addon source.
        output_dir (str): Directory path to output zip file.
        addon_output_dir (str): Directory path to addon output directory.
        addon_version (str): Version of addon.
        log (logging.Logger): Logger object.

    """
    log.info("Creating server package")
    output_path = os.path.join(
        output_dir, f"{ADDON_NAME}-{addon_version}.zip"
    )
    with ZipFileLongPaths(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Write a manifest to zip
        zipf.write(
            os.path.join(current_dir, "package.py"), "package.py"
        )

        # Move addon content to zip into 'addon' directory
        addon_output_dir_offset = len(addon_output_dir) + 1
        for root, _, filenames in os.walk(addon_output_dir):
            if not filenames:
                continue

            dst_root = None
            if root != addon_output_dir:
                dst_root = root[addon_output_dir_offset:]
            for filename in filenames:
                src_path = os.path.join(root, filename)
                dst_path = filename
                if dst_root:
                    dst_path = os.path.join(dst_root, filename)
                zipf.write(src_path, dst_path)

    log.info(f"Output package can be found: {output_path}")


def main(
    output_dir: Optional[str] = None,
    skip_zip: bool = False,
    keep_sources: bool = False
):
    """Create addon package.

    Main function to execute package creation.

    Args:
        output_dir (str, optional): Output directory path.
        skip_zip (bool): Skip zipping server package.
        keep_sources (bool): Keep sources when server package is created.

    """
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("create_package")
    log.setLevel(logging.INFO)

    log.info("Start creating package")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    if not output_dir:
        output_dir = os.path.join(current_dir, "package")

    downloads_dir = Path(os.path.join(current_dir, "downloads"))
    downloads_dir.mkdir(exist_ok=True)

    files_info = download_usd_zip(downloads_dir, log)

    new_created_version_dir = os.path.join(
        output_dir, ADDON_NAME, ADDON_VERSION
    )
    if os.path.isdir(new_created_version_dir):
        log.info(f"Purging {new_created_version_dir}")
        shutil.rmtree(output_dir)

    _fill_client_version(current_dir)

    log.info(f"Preparing package for {ADDON_NAME}-{ADDON_VERSION}")

    addon_output_root = os.path.join(output_dir, ADDON_NAME)
    addon_output_dir = os.path.join(addon_output_root, ADDON_VERSION)
    if not os.path.exists(addon_output_dir):
        os.makedirs(addon_output_dir)

    copy_server_content(addon_output_dir, current_dir, log)

    private_dir = Path(addon_output_dir) / "private"
    if not private_dir.exists():
        private_dir.mkdir(parents=True)

    for file_info in files_info:
        filename = file_info["filename"]
        src_path = downloads_dir / filename
        dst_path = private_dir / filename
        shutil.copy(src_path, dst_path)

    zips_info_path = private_dir / "files_info.json"
    with open(zips_info_path, "w") as stream:
        json.dump(files_info, stream)

    zip_client_side(addon_output_dir, current_dir, log)

    # Skip server zipping
    if not skip_zip:
        create_server_package(
            current_dir, output_dir, addon_output_dir, ADDON_VERSION, log
        )
        # Remove sources only if zip file is created
        if not keep_sources:
            log.info("Removing source files for server package")
            shutil.rmtree(addon_output_root)
    log.info("Package creation finished")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-zip",
        dest="skip_zip",
        action="store_true",
        help=(
            "Skip zipping server package and create only"
            " server folder structure."
        )
    )
    parser.add_argument(
        "--keep-sources",
        dest="keep_sources",
        action="store_true",
        help=(
            "Keep folder structure when server package is created."
        )
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_dir",
        default=None,
        help=(
            "Directory path where package will be created"
            " (Will be purged if already exists!)"
        )
    )

    args = parser.parse_args(sys.argv[1:])
    main(args.output_dir, args.skip_zip, args.keep_sources)
