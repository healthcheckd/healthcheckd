#!/bin/bash
set -euo pipefail
export PATH="/usr/local/bin:${PATH}"

echo "=== Installing build dependencies ==="
dnf install -y rpm-build

echo "=== Building RPM ==="
cd /tmp
rm -rf build-healthcheckd
cp -r /vagrant build-healthcheckd
cd build-healthcheckd

VERSION="1.2.0"
RELEASE="1"
GITHUB_REPO_NAME="healthcheckd"
DESCRIPTION="Health check daemon for AWS ALB/NLB with Prometheus metrics"
RPM_ARCHITECTURE="noarch"
REQUIRES="python3, python3-aiohttp, python3-pyyaml, python3-prometheus_client"

mkdir -p SOURCES/${GITHUB_REPO_NAME}/{usr/bin,usr/lib/healthcheckd,usr/lib/systemd/system,usr/share/doc/${GITHUB_REPO_NAME},etc/healthcheckd/config.d} SPECS

cp packaging/healthcheckd-wrapper SOURCES/${GITHUB_REPO_NAME}/usr/bin/healthcheckd
cp -r src/healthcheckd SOURCES/${GITHUB_REPO_NAME}/usr/lib/healthcheckd/healthcheckd
cp packaging/healthcheckd.service SOURCES/${GITHUB_REPO_NAME}/usr/lib/systemd/system/healthcheckd.service
cp LICENSE SOURCES/${GITHUB_REPO_NAME}/usr/share/doc/${GITHUB_REPO_NAME}/LICENSE
cp packaging/config SOURCES/${GITHUB_REPO_NAME}/etc/healthcheckd/config
cp packaging/config.d/example.yaml SOURCES/${GITHUB_REPO_NAME}/etc/healthcheckd/config.d/example.yaml

cat > SPECS/${GITHUB_REPO_NAME}.spec << SPEC
Name:      ${GITHUB_REPO_NAME}
Version:   ${VERSION}
Release:   ${RELEASE}
Summary:   ${DESCRIPTION}
BuildArch: ${RPM_ARCHITECTURE}
Source0:   %{name}
License:   Unlicense
Requires:  ${REQUIRES}

%description
${DESCRIPTION}

%pre
getent group healthcheckd >/dev/null 2>&1 || groupadd --system healthcheckd
getent passwd healthcheckd >/dev/null 2>&1 || useradd --system --gid healthcheckd --no-create-home --shell /usr/sbin/nologin healthcheckd

%post
if [ -d /run/systemd/system ]; then
  systemctl daemon-reload || true
fi

%prep

%build

%install
install -D -m 755 -o root -g root %{SOURCE0}/usr/bin/healthcheckd \${RPM_BUILD_ROOT}/usr/bin/healthcheckd
install -D -m 644 -o root -g root %{SOURCE0}/usr/lib/systemd/system/healthcheckd.service \${RPM_BUILD_ROOT}/usr/lib/systemd/system/healthcheckd.service
install -D -m 644 -o root -g root %{SOURCE0}/etc/healthcheckd/config \${RPM_BUILD_ROOT}/etc/healthcheckd/config
install -D -m 644 -o root -g root %{SOURCE0}/etc/healthcheckd/config.d/example.yaml \${RPM_BUILD_ROOT}/etc/healthcheckd/config.d/example.yaml
install -D -m 644 -o root -g root %{SOURCE0}/usr/share/doc/healthcheckd/LICENSE \${RPM_BUILD_ROOT}/usr/share/doc/healthcheckd/LICENSE
$(find SOURCES/${GITHUB_REPO_NAME}/usr/lib/healthcheckd -type f | while read -r f; do
  rel="${f#SOURCES/${GITHUB_REPO_NAME}/}"
  echo "install -D -m 644 -o root -g root %{SOURCE0}/${rel} \${RPM_BUILD_ROOT}/${rel}"
done)

%files
/usr/bin/healthcheckd
/usr/lib/systemd/system/healthcheckd.service
/etc/healthcheckd/config
/etc/healthcheckd/config.d/example.yaml
/usr/share/doc/healthcheckd/LICENSE
$(find SOURCES/${GITHUB_REPO_NAME}/usr/lib/healthcheckd -type f | while read -r f; do
  echo "/${f#SOURCES/${GITHUB_REPO_NAME}/}"
done)
SPEC

rpmbuild --define "_topdir $(pwd)" -bb SPECS/${GITHUB_REPO_NAME}.spec

RPM_FILE=$(find RPMS/ -name '*.rpm' -type f)
echo "=== RPM built: ${RPM_FILE} ==="

echo "=== Installing EPEL (for python3-aiohttp) ==="
dnf install -y epel-release

echo "=== Installing RPM ==="
rpm -e healthcheckd 2>/dev/null || true
dnf install -y "${RPM_FILE}"

echo "=== Verifying installation ==="
echo "Binary:  $(ls -la /usr/bin/healthcheckd)"
echo "Service: $(ls -la /usr/lib/systemd/system/healthcheckd.service)"
echo "Config:  $(ls -la /etc/healthcheckd/config)"
echo "User:    $(getent passwd healthcheckd)"
echo "Group:   $(getent group healthcheckd)"

echo "=== Creating test check config ==="
cat > /etc/healthcheckd/config.d/tcp_ssh.yaml << 'CHECK'
type: tcp
host: 127.0.0.1
port: 22
CHECK

echo "=== Starting healthcheckd service ==="
systemctl stop healthcheckd 2>/dev/null || true
systemctl reset-failed healthcheckd 2>/dev/null || true
systemctl daemon-reload
systemctl start healthcheckd
sleep 3

echo "=== Service status ==="
systemctl status healthcheckd --no-pager

echo ""
echo "=== Testing /simple endpoint ==="
SIMPLE_CODE=$(curl -s -o /tmp/simple_body -w '%{http_code}' http://localhost:9990/simple)
echo "HTTP ${SIMPLE_CODE}"
cat /tmp/simple_body
echo ""

echo ""
echo "=== Testing /complex endpoint ==="
COMPLEX_CODE=$(curl -s -o /tmp/complex_body -w '%{http_code}' http://localhost:9990/complex)
echo "HTTP ${COMPLEX_CODE}"
cat /tmp/complex_body
echo ""

echo ""
echo "=== Testing /metrics endpoint ==="
METRICS_CODE=$(curl -s -o /tmp/metrics_body -w '%{http_code}' http://localhost:9990/metrics)
echo "HTTP ${METRICS_CODE}"
head -20 /tmp/metrics_body
echo ""

echo ""
echo "========================================="
if [ "${SIMPLE_CODE}" = "200" ] && [ "${METRICS_CODE}" = "200" ]; then
    echo "  ALL CHECKS PASSED"
else
    echo "  CHECKS FAILED (simple=${SIMPLE_CODE}, metrics=${METRICS_CODE})"
    exit 1
fi
echo "========================================="
