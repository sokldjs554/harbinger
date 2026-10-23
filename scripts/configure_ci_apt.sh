#!/usr/bin/env bash
# GitHub's regional Azure package mirror intermittently stalled font downloads.
set -euo pipefail
for source in /etc/apt/apt-mirrors.txt /etc/apt/apt-security-mirrors.txt /etc/apt/sources.list /etc/apt/sources.list.d/ubuntu.sources; do
    if [[ -f "$source" ]]; then
        sudo sed -i \
            -e 's|http://azure.archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g' \
            -e 's|https://azure.archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g' "$source"
    fi
done
printf 'Acquire::http::Timeout "30";\nAcquire::https::Timeout "30";\nAcquire::Retries "2";\n' | sudo tee /etc/apt/apt.conf.d/80-harbinger-ci-network >/dev/null
