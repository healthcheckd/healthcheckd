#!/bin/sh
export GITHUB_REPO_NAME
export GITHUB_REF_NAME
mkdir -p SPECS
(
    echo "Name:      ${GITHUB_REPO_NAME}"
    echo "Version:   ${VERSION}"
    echo "Release:   ${RELEASE}"
    echo "Summary:   ${DESCRIPTION}"
    echo "BuildArch: ${RPM_ARCHITECTURE:-x86_64}"
    echo "Source0:   %{name}"
    echo "License:   ${LICENSE:-Unlicense}"
    if [ -n "${REQUIRES}" ]
    then
        echo "Requires:  ${REQUIRES}"
    fi
    if [ -n "${HOMEPAGE}" ]
    then
        echo "URL:       ${HOMEPAGE}"
    fi
    echo ""
    echo "%description"
    echo "${DESCRIPTION}"
    echo ""
    echo "%pre"
    echo "getent group healthcheckd >/dev/null 2>&1 || groupadd --system healthcheckd"
    echo "getent passwd healthcheckd >/dev/null 2>&1 || useradd --system --gid healthcheckd --no-create-home --shell /usr/sbin/nologin healthcheckd"
    echo ""
    echo "%post"
    echo "if [ -d /run/systemd/system ]; then"
    echo "  systemctl daemon-reload || true"
    echo "fi"
    echo ""
    echo "%prep"
    echo ""
    echo "%build"
    echo ""
    echo "%install"
    find "SOURCES/${GITHUB_REPO_NAME}/etc" "SOURCES/${GITHUB_REPO_NAME}/usr" -type f -exec exec_install_file '{}' \;
    echo ""
    echo "%files"
    find "SOURCES/${GITHUB_REPO_NAME}/etc" "SOURCES/${GITHUB_REPO_NAME}/usr" -type f -exec strip_rpm_root '{}' \;
) | tee "SPECS/${GITHUB_REPO_NAME}.spec"
