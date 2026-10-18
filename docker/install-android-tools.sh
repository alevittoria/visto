#!/bin/sh
# Install pinned Android SDK archives into $ANDROID_HOME without sdkmanager.
# URLs and SHA-1 checksums come from Google's SDK repository manifest
# (https://dl.google.com/android/repository/repository2-3.xml); every image uses
# the same platform-tools so adb clients and the shared server never mismatch.
# These archives are distributed under the Android SDK license terms.
set -eu

ANDROID_HOME=${ANDROID_HOME:?ANDROID_HOME must be set}
REPOSITORY=https://dl.google.com/android/repository

install_archive() {
    archive=$1 sha1=$2 target=$3
    work=$(mktemp -d)
    curl -fsSL --retry 3 -o "$work/$archive" "$REPOSITORY/$archive"
    echo "$sha1  $work/$archive" | sha1sum -c -
    unzip -q "$work/$archive" -d "$work/unpacked"
    # Each archive holds exactly one top-level directory (its name varies).
    set -- "$work"/unpacked/*
    [ $# -eq 1 ] && [ -d "$1" ] || { echo "Unexpected layout in $archive" >&2; exit 1; }
    mkdir -p "$(dirname "$ANDROID_HOME/$target")"
    mv "$1" "$ANDROID_HOME/$target"
    rm -rf "$work"
}

for component in "$@"; do
    case "$component" in
        platform-tools)
            install_archive platform-tools_r37.0.1-linux.zip \
                477254aa5f903c15cf51001717bdf347fb6b53e0 platform-tools ;;
        build-tools)
            # UiAutomator2 needs apksigner to verify its server APK signatures.
            install_archive build-tools_r37_linux.zip \
                70954e99f4c3d9d46ee70fa32624672fe7cd6ebe build-tools/37.0.0 ;;
        *)
            echo "Unknown component: $component" >&2; exit 2 ;;
    esac
done
