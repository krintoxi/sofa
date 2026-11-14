plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val build = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()

// The Google TV build's own signing key: never in the repository. It comes from the environment (GitHub's secrets,
// or your own shell) when it's there; without it the release is built unsigned, for Google Play's own signing or
// yours. See android/README.md, "Android TV and Google TV".
val storeKey: String? = System.getenv("SOFA_TV_KEYSTORE")?.takeIf { it.isNotBlank() && file(it).exists() }

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
    // The Fire TV app: one key for every build, so a new version installs over the old one. It's only for
    // installing your own copy (see android/README.md): anyone can sign with it, so only install Sofa from your
    // own server or this repository's Releases page. The Google TV app is never signed with it.
    signingConfigs {
        create("sideload") {
            storeFile = file("../sofa-sideload.jks")
            storePassword = "sofa-sideload"
            keyAlias = "sofa"
            keyPassword = "sofa-sideload"
        }
        if (storeKey != null) {
            create("store") {
                storeFile = file(storeKey)
                storePassword = System.getenv("SOFA_TV_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("SOFA_TV_KEY_ALIAS")
                keyPassword = System.getenv("SOFA_TV_KEY_PASSWORD")
            }
        }
    }
    // One app, two devices. `firetv`: what has shipped since the first build (the same name and key, so it installs
    // over the one on a Fire TV). `googletv`: Android TV and Google TV, under a name of its own, so the public
    // sideload key can never sign something that installs over it.
    flavorDimensions += "device"
    productFlavors {
        create("firetv") {
            dimension = "device"
            signingConfig = signingConfigs.getByName("sideload")
            buildConfigField("String", "DEVICE", "\"FireTV\"")
            buildConfigField("String", "DEVICE_NAME", "\"Fire TV\"")
        }
        create("googletv") {
            dimension = "device"
            applicationId = "uk.edgeventure.sofa.tv"
            signingConfig = signingConfigs.findByName("store")
            buildConfigField("String", "DEVICE", "\"GoogleTV\"")
            buildConfigField("String", "DEVICE_NAME", "\"Google TV\"")
        }
    }
    buildTypes {
        getByName("release") {
            isMinifyEnabled = false         // (its signing is the device's: see the flavors)
        }
    }
    buildFeatures { buildConfig = true }
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
