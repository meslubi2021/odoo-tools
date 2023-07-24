plugins {
    id("cli-application")
    id("launcher-checksums")
    alias(libs.plugins.kotlinx.plugin.serialization)
}

cli {
    name = "odoo"
    mainClass = "com.github.hubvd.odootools.odoo.OdooKt"
}

dependencies {
    implementation(project(":config"))
    implementation(project(":workspace"))
    implementation(libs.coroutines.core)
    implementation(libs.process)
    implementation(libs.xmlbuilder)
    implementation(libs.kodein.di)
    implementation(libs.kotlin.reflect)
    implementation(libs.serialization.json)
}

spotless {
    python {
        target("resources/launcher/**/*.py")
        black("23.7.0")
    }
    json {
        target("resources/odoo/META-INF/native-image/*.json")
        gson()
            .indentWithSpaces(4)
            .sortByKeys()
    }
}
