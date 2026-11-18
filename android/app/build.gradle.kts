// 김비서 폰 앱 — 내 PC 의 김비서와 짝지어 말·글로 대화(같은 와이파이 · 테일스케일은 선택)
//   서버 주소·열쇠는 앱에 들어 있지 않다: 짝지을 때 PC 화면의 QR(또는 주소 + 8자리 코드)로 받는다.
//   서명: 직접 만드는 사람이 자기 열쇠로(환경변수 KIMBISEO_KS_FILE · KIMBISEO_KS_PASS · KIMBISEO_KS_ALIAS). 없으면 서명 안 된 release.
//   시험판: KIMBISEO_TEST=1 이면 TEST_HOOKS(파일 소리 넣기·시험 명령) 켬 — 배포판은 꺼짐.
plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "kr.kimbiseo.phone"; compileSdk = 36
    defaultConfig {
        applicationId = "kr.kimbiseo.phone"; minSdk = 26; targetSdk = 36
        versionCode = 1; versionName = "0.1.0"
        buildConfigField("boolean", "TEST_HOOKS", if (System.getenv("KIMBISEO_TEST") == "1") "true" else "false")
        val abis = System.getenv("KIMBISEO_ABIS") ?: ""
        if (abis.isNotEmpty()) ndk { abiFilters += abis.split(",") }
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    val ksFile = System.getenv("KIMBISEO_KS_FILE") ?: ""
    if (ksFile.isNotEmpty()) signingConfigs { create("rel") {
        storeFile = file(ksFile); storePassword = System.getenv("KIMBISEO_KS_PASS") ?: ""
        keyAlias = System.getenv("KIMBISEO_KS_ALIAS") ?: "kimbiseo"; keyPassword = System.getenv("KIMBISEO_KS_PASS") ?: "" } }
    buildTypes { release { if (ksFile.isNotEmpty()) signingConfig = signingConfigs.getByName("rel"); isMinifyEnabled = false } }
    buildFeatures { buildConfig = true }
    lint { abortOnError = false; checkReleaseBuilds = false }
}
dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")              // Apache-2.0 — HTTPS·WSS(PC 인증서 지문 고정)
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")    // Apache-2.0 — 앱 안에서 QR 찍기
    testImplementation("junit:junit:4.13.2")
}
