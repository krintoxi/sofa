plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val build = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()

android {
    namespace = "uk.edgeventure.sofa"
    compileSdk = 34
    defaultConfig {
        applicationId = "uk.edgeventure.sofa"
        minSdk = 22                     // Fire OS 5 (2015 Fire TV sticks) and newer
        targetSdk = 34
        versionCode = build
        versionName = "1.0.$build"
    }
    // One key for every build, so a new version installs over the old one. It's only for installing
    // your own copy (see android/README.md): anyone can sign with it, so only install Sofa from your
    // own server or this repository's Releases page.
    signingConfigs {
        create("sideload") {
            storeFile = file("../sofa-sideload.jks")
            storePassword = "sofa-sideload"
            keyAlias = "sofa"
            keyPassword = "sofa-sideload"
        }
    }
    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("sideload")
        }
        getByName("debug") {
            signingConfig = signingConfigs.getByName("sideload")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    lint {
        checkReleaseBuilds = false      // built on GitHub; nothing here needs Android lint to stop a release
        abortOnError = false
    }
}

dependencies {
    implementation("androidx.media3:media3-exoplayer:1.4.1")
    implementation("androidx.media3:media3-exoplayer-hls:1.4.1")
    implementation("androidx.media3:media3-ui:1.4.1")
}
