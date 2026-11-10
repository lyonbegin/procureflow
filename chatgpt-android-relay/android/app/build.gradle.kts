plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "com.hitel.chatrelay"
    compileSdk = 35
    defaultConfig { applicationId = "com.hitel.chatrelay"; minSdk = 29; targetSdk = 35; versionCode = 6; versionName = "0.6.0-legacy-chat-pairing" }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}
dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.core:core:1.13.1")
}
