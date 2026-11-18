#!/bin/bash
# Security fixes on top of the bullseye KasmVNC base (2026-10-22). Runs at the end of the
# Dockerfile, and in the patch image built FROM the previous mt5-mt5 image (see README:
# "Security patch image") because a full rebuild of this image is not reliable.
#  - bind9-host / bind9-libs: CVE-2026-3039, CVE-2026-5946 (bullseye-security 1:9.16.50-1~deb11u6).
#    Debian 11 is out of support: its security archive moved to archive.debian.org, and
#    security.debian.org still lists the fix but answers 404 for the file. A temporary source
#    list fetches only these packages from there; the image's own apt sources stay as they are.
#  - xserver-common / xserver-xorg-core: CVE-2026-34000, CVE-2026-34002 (bullseye-security
#    2:1.20.11-1+deb11u18), from the same archive
#  - kclient's proxy-addr 2.0.7 -> 2.0.8: GHSA-jqcg-44mw-7w3h
#  - kclient's ws 8.17.1 -> 8.21.0: GHSA-96hv-2xvq-fx4p (memory exhaustion DoS). engine.io pins
#    ~8.17.1, but ws keeps its API within 8.x and has no dependencies.
#  - the npm CLI that comes with nodesource Node: never used at runtime here, and it bundles
#    vulnerable glob, ip, semver and tar
set -euo pipefail

echo "deb http://archive.debian.org/debian-security bullseye-security main" > /tmp/bullseye-security-archive.list
ARCHIVE=(-o Dir::Etc::SourceList=/tmp/bullseye-security-archive.list -o Dir::Etc::SourceParts=- -o Acquire::Check-Valid-Until=false)
apt-get "${ARCHIVE[@]}" update
DEBIAN_FRONTEND=noninteractive apt-get "${ARCHIVE[@]}" install -y --only-upgrade \
  bind9-host bind9-libs xserver-common xserver-xorg-core
rm -rf /var/lib/apt/lists/* /tmp/bullseye-security-archive.list

wget -q -O /tmp/proxy-addr.tgz https://registry.npmjs.org/proxy-addr/-/proxy-addr-2.0.8.tgz
echo "e679f1d321b2554718eadf519d6700456b704fd1750fc3bdaedd3c86d3ef9dde3d5b522066d98b921bbd59f333423d5c1718c720ee9ca279d43555b993b015c9  /tmp/proxy-addr.tgz" \
  | sha512sum -c -
rm -rf /kclient/node_modules/proxy-addr
mkdir /kclient/node_modules/proxy-addr
tar xzf /tmp/proxy-addr.tgz -C /kclient/node_modules/proxy-addr --strip-components=1 --no-same-owner
rm /tmp/proxy-addr.tgz

wget -q -O /tmp/ws.tgz https://registry.npmjs.org/ws/-/ws-8.21.0.tgz
echo "56ca76f1bec345c8a6150bebaaed967a4df3d626310c25aa1d807c42c9e4fd2e117da090ccf18fc8136e563255ddc77a5222ad52da7ab0d33bee05afcdc087fa  /tmp/ws.tgz" \
  | sha512sum -c -
rm -rf /kclient/node_modules/ws
mkdir /kclient/node_modules/ws
tar xzf /tmp/ws.tgz -C /kclient/node_modules/ws --strip-components=1 --no-same-owner
rm /tmp/ws.tgz

rm -rf /usr/lib/node_modules/npm /usr/bin/npm /usr/bin/npx
