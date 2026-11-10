import java.security.MessageDigest

plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

val serverAbi = providers.gradleProperty("serverAbi").orElse("arm64-v8a").get()
require(serverAbi in listOf("arm64-v8a", "x86_64")) { "serverAbi must be arm64-v8a or x86_64" }
val serverData = providers.gradleProperty("serverData").map { rootProject.file(it) }
    .orElse(rootProject.file("../data/clients/IdolyPride-ServerData-v0.2.16.zip"))
val payloadFile = serverData.get()
val payloadHash = if (payloadFile.isFile) payloadFile.inputStream().use { input ->
    val digest = MessageDigest.getInstance("SHA-256")
    val buffer = ByteArray(64 * 1024)
    var count = input.read(buffer)
    while (count >= 0) {
        if (count > 0) digest.update(buffer, 0, count)
        count = input.read(buffer)
    }
    digest.digest().joinToString("") { "%02x".format(it) }
} else "missing"
val generatedAssets = layout.buildDirectory.dir("generated/serverDataAssets")
val prepareServerDataAssets = tasks.register<Copy>("prepareServerDataAssets") {
    inputs.file(serverData)
    from(serverData) { rename { "ServerData.zip" } }
    into(generatedAssets)
    doFirst {
        require(payloadFile.isFile) { "Provide ServerData.zip with -PserverData=/absolute/path/ServerData.zip" }
    }
}

android {
    namespace = "game.qualiarts.idolypride.localserver"
    compileSdk = 34
    defaultConfig {
        applicationId = "game.qualiarts.idolypride.localserver"
        minSdk = 26
        targetSdk = 34
        versionCode = providers.gradleProperty("serverVersionCode").orElse("18").get().toInt()
        versionName = providers.gradleProperty("serverVersionName").orElse("0.2.16").get()
        ndk { abiFilters += serverAbi }
        buildConfigField("String", "SERVER_DATA_SHA256", "\"$payloadHash\"")
    }
    buildFeatures { buildConfig = true }
    signingConfigs {
        create("publicDevelopment") {
            // This committed development key is intentionally public. Reusing
            // it lets experimental server updates preserve the app's local DB.
            storeFile = rootProject.file("local-server-development.keystore")
            storePassword = "android"
            keyAlias = "idoly-local-server"
            keyPassword = "android"
        }
        val releaseStore = System.getenv("IDOLY_SERVER_KEYSTORE")
        if (!releaseStore.isNullOrBlank()) {
            create("privateRelease") {
                storeFile = file(releaseStore)
                storePassword = requireNotNull(System.getenv("IDOLY_SERVER_STORE_PASSWORD"))
                keyAlias = requireNotNull(System.getenv("IDOLY_SERVER_KEY_ALIAS"))
                keyPassword = requireNotNull(System.getenv("IDOLY_SERVER_KEY_PASSWORD"))
            }
        }
    }
    buildTypes {
        debug { signingConfig = signingConfigs.getByName("publicDevelopment") }
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("privateRelease") ?: signingConfigs.getByName("publicDevelopment")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets.getByName("main").assets.srcDir(generatedAssets)
    androidResources { noCompress += "zip" }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        providers.gradleProperty("buildPython").orNull?.let { buildPython(it) }
        pip {
            // Both packages and their dependencies have universal Python wheels.
            // No grpcio or native PyCryptodome Android wheel is required.
            options("--only-binary=:all:")
            install("protobuf==6.33.0")
            install("h2==4.3.0")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir("src/main/python")
            srcDir("../../src")
        }
    }
}

tasks.named("preBuild").configure { dependsOn(prepareServerDataAssets) }
