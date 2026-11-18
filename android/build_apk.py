# 김비서 폰 앱 만들기 — 이 폴더(android)를 영문 경로 빌드 폴더로 복사해 gradle 로 APK 를 만든다(한글 경로에서 gradle 이 깨지는 것 피함).
#   필요: JDK 17+, 안드로이드 SDK(platform 36, build-tools 36), gradle 8.7~8.9 (gradle 실행 파일 경로를 --gradle 또는 환경변수 GRADLE).
#   서명: 자기 열쇠로 — 환경변수 KIMBISEO_KS_FILE(절대 경로) · KIMBISEO_KS_PASS · KIMBISEO_KS_ALIAS. 없으면 서명 안 된 APK(직접 apksigner 로 서명).
#   python build_apk.py [--test] [--unit] [--out 폴더] [--sdk C:\android-sdk] [--gradle C:\gradle-8.7\bin\gradle.bat]
#     --test : 시험판(TEST_HOOKS — adb 로 짝짓기·소리 넣기). 배포하지 말 것.
#     --unit : 단위 시험(PairRules·NavRules·NameRules·AppRules)만 돌림.
import argparse
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--unit", action="store_true")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--sdk", default=os.environ.get("ANDROID_HOME") or r"C:\android-sdk")
    ap.add_argument("--gradle", default=os.environ.get("GRADLE") or r"C:\gradle-8.7\bin\gradle.bat")
    ap.add_argument("--build", default=os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Temp", "kimbiseo_android_build"))
    a = ap.parse_args()
    if os.path.exists(a.build):
        shutil.rmtree(a.build)
    shutil.copytree(HERE, a.build, ignore=shutil.ignore_patterns("build", ".gradle", "out", "*.jks", "local.properties"))
    with open(os.path.join(a.build, "local.properties"), "w", encoding="utf-8") as f:
        f.write("sdk.dir=" + a.sdk.replace("\\", "\\\\").replace(":", "\\:") + "\n")
    env = dict(os.environ, ANDROID_HOME=a.sdk)
    if a.test:
        env["KIMBISEO_TEST"] = "1"
    else:
        env.pop("KIMBISEO_TEST", None)
    tasks = [":app:testReleaseUnitTest"] if a.unit else [":app:testReleaseUnitTest", ":app:assembleRelease"]
    r = subprocess.run([a.gradle, "--no-daemon", "-q", *tasks], cwd=a.build, env=env)
    if r.returncode:
        sys.exit("빌드 실패")
    if a.unit:
        print("단위 시험 통과")
        return
    apks = glob.glob(os.path.join(a.build, "app", "build", "outputs", "apk", "release", "*.apk"))
    if not apks:
        sys.exit("APK 를 못 찾았어요")
    os.makedirs(a.out, exist_ok=True)
    signed = bool(env.get("KIMBISEO_KS_FILE"))
    name = "kimbiseo-phone-" + ("test" if a.test else "release") + ("" if signed else "-unsigned") + ".apk"
    dst = os.path.join(a.out, name)
    shutil.copy2(apks[0], dst)
    print(dst)


if __name__ == "__main__":
    main()
