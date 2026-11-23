#!/bin/sh
# 맥북에서 경고 판단 로직 단위 테스트를 컴파일·실행한다. 외부 의존성 없음.
set -eu
cd "$(dirname "$0")/.."
mkdir -p .build
c++ -std=c++17 -Wall -Wextra -Werror -Ilib/core \
  lib/core/keyring_packet.cpp lib/core/warning_controller.cpp test/test_core.cpp \
  -o .build/test_core
./.build/test_core
