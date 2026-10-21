set -e
python - <<'PY'
from pathlib import Path
import shutil
p=Path('/tmp/abba-family-sanitized-source')
if not p.exists():shutil.copytree('adapters/abba_family/vendor/abba_family',p)
PY
cmake -S /tmp/abba-family-sanitized-source -B /tmp/abba-family-sanitized -DCMAKE_BUILD_TYPE=RelWithDebInfo -DAF_SANITIZE=ON -DBUILD_TESTING=OFF > /tmp/abba-asan-build.log 2>&1
cmake --build /tmp/abba-family-sanitized --target abba_family -j2 >> /tmp/abba-asan-build.log 2>&1
for key in abba fabba qabba; do
c++ -std=c++17 -O1 -g -fPIC -shared -fno-fast-math -ffp-contract=off -fsanitize=address,undefined -fno-omit-frame-pointer -DAF_KEY=\"$key\" -I native/include -I adapters/abba_family/vendor/abba_family/include -I adapters/abba_family/vendor/abba_family/vendor/zlib adapters/abba_family/native/binding.cc -L /tmp/abba-family-sanitized -labba_family -Wl,-rpath,/tmp/abba-family-sanitized -Wl,-Bsymbolic-functions -o /tmp/abba-family-sanitized/libtscb_$key.so >> /tmp/abba-asan-build.log 2>&1
done
