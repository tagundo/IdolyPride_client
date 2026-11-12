import java.security.MessageDigest
import java.nio.ByteBuffer
import java.nio.ByteOrder

plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

val serverAbi = providers.gradleProperty("serverAbi").orElse("arm64-v8a").get()
require(serverAbi in listOf("arm64-v8a", "x86_64")) { "serverAbi must be arm64-v8a or x86_64" }
val serverData = providers.gradleProperty("serverData").map { rootProject.file(it) }
    .orElse(rootProject.file("../data/clients/IdolyPride-ServerData-v0.3.8.zip"))
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

// Optional prebuilt libraries only. Go sources never enter Chaquopy's Python
// package, and omitting this property removes any previously staged library.
val liveEngineDir = providers.gradleProperty("liveEngineDir").map { rootProject.file(it) }
val liveEngineLibrary = liveEngineDir.map { it.resolve("$serverAbi/libidoly_live.so") }
val liveEngineNotices = rootProject.file("../native-live-engine")
val liveEngineNoticePaths = listOf("LICENSE", "NOTICE", "third-party-licenses/Go-LICENSE",
    "third-party-licenses/Protobuf-LICENSE", "third-party-licenses/YAML-LICENSE",
    "third-party-licenses/YAML-NOTICE")
val generatedLiveEngine = layout.buildDirectory.dir("generated/optionalLiveEngine")
val prepareLiveEngine = tasks.register("prepareLiveEngine") {
    inputs.property("liveEngineDir", liveEngineDir.map { it.absolutePath }.orElse(""))
    inputs.property("serverAbi", serverAbi)
    if (liveEngineLibrary.isPresent) {
        inputs.file(liveEngineLibrary)
        inputs.files(liveEngineNoticePaths.map { liveEngineNotices.resolve(it) })
    }
    outputs.dir(generatedLiveEngine)
    doLast {
        val library = liveEngineLibrary.orNull
        if (library != null) {
            require(library.isFile) { "liveEngineDir must contain $serverAbi/libidoly_live.so" }
            val raw = library.readBytes()
            require(raw.size >= 64 && raw.copyOfRange(0, 6).contentEquals(byteArrayOf(0x7f, 0x45, 0x4c, 0x46, 2, 1))) {
                "libidoly_live.so must be a 64-bit little-endian ELF library"
            }
            val elf = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN)
            val expectedMachine = if (serverAbi == "arm64-v8a") 183 else 62
            require(elf.getShort(16).toInt() == 3 && elf.getShort(18).toInt() == expectedMachine) {
                "libidoly_live.so does not match the selected serverAbi=$serverAbi"
            }
            require(liveEngineNoticePaths.all { liveEngineNotices.resolve(it).isFile }) {
                "Native live engine LICENSE, NOTICE and third-party notices must be present"
            }
        }
        val destination = generatedLiveEngine.get().asFile
        project.delete(destination)
        destination.mkdirs()
        if (library != null) {
            val outputLibrary = destination.resolve("jniLibs/$serverAbi/libidoly_live.so")
            outputLibrary.parentFile.mkdirs()
            library.copyTo(outputLibrary)
            for (relative in liveEngineNoticePaths) {
                val outputNotice = destination.resolve("assets/native-live-engine/$relative")
                outputNotice.parentFile.mkdirs()
                liveEngineNotices.resolve(relative).copyTo(outputNotice)
            }
        }
    }
}

android {
    namespace = "game.qualiarts.idolypride.localserver"
    compileSdk = 34
    defaultConfig {
        applicationId = "game.qualiarts.idolypride.localserver"
        minSdk = 26
        targetSdk = 34
        versionCode = providers.gradleProperty("serverVersionCode").orElse("35").get().toInt()
        versionName = providers.gradleProperty("serverVersionName").orElse("0.3.16").get()
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
            isDebuggable = false
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("privateRelease") ?: signingConfigs.getByName("publicDevelopment")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets.getByName("main").assets.srcDir(generatedAssets)
    sourceSets.getByName("main").assets.srcDir(generatedLiveEngine.map { it.dir("assets") })
    sourceSets.getByName("main").jniLibs.srcDir(generatedLiveEngine.map { it.dir("jniLibs") })
    if (liveEngineDir.isPresent) {
        packaging.jniLibs {
            // ctypes uses applicationInfo.nativeLibraryDir. Extract this
            // optional library rather than depending on an APK zip pathname.
            useLegacyPackaging = true
            keepDebugSymbols += "**/libidoly_live.so"
        }
    }
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
            exclude("**/*.go", "**/go.mod", "**/go.sum", "**/native-live-engine/**")
            // Match the manual server package: these offline CLI, client
            // patch/build and QA modules are outside the server dependency
            // closure. Keep exact filenames so runtime modules remain intact.
            exclude("idoly_local/__main__.py", "idoly_local/cli.py", "idoly_local/android_package.py",
                "idoly_local/client_patch.py", "idoly_local/native_bootstrap.py", "idoly_local/ios_patch.py",
                "idoly_local/ios_presentation.py", "idoly_local/master_build.py", "idoly_local/media_master_build.py",
                "idoly_local/unity_http.py", "idoly_local/unity_cache.py", "idoly_local/collect.py",
                "idoly_local/event_capture.py", "idoly_local/firebase_archive.py", "idoly_local/official_session.py",
                "idoly_local/profiles.py", "idoly_local/server.py", "idoly_local/appearance_qa.py",
                "idoly_local/lesson_qa.py", "idoly_local/main_live_qa.py", "idoly_local/story_qa.py",
                "idoly_local/story_read_qa.py", "idoly_local/tutorial_qa.py", "idoly_local/pvp_capture.py")
        }
    }
}

tasks.named("preBuild").configure { dependsOn(prepareServerDataAssets, prepareLiveEngine) }
