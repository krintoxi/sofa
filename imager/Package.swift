// swift-tools-version:5.9
// Sofa Box Imager: EdgeVenture's own app for writing Sofa Box OS cards (Raspberry Pi 3 B+, 4 and 5). macOS 13 or newer.
import PackageDescription

let package = Package(
    name: "SofaBoxImager",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "SofaBoxImager", targets: ["SofaBoxImager"]),
    ],
    targets: [
        // Spawns /usr/libexec/authopen and receives the disk's file descriptor from it (C: SCM_RIGHTS needs the CMSG macros).
        .target(name: "CAuthOpen"),
        // Pure Swift, no disks: the list, which disks may be written (DiskPolicy), the xz decoder, the write-and-verify engine.
        .target(name: "ImagerKit"),
        // macOS: DiskArbitration and IOKit (finding, unmounting and ejecting disks), authopen, keeping the Mac awake.
        .target(name: "ImagerMac", dependencies: ["ImagerKit", "CAuthOpen"],
                linkerSettings: [.linkedFramework("DiskArbitration"), .linkedFramework("IOKit"),
                                 .linkedFramework("Security")]),
        .executableTarget(name: "SofaBoxImager", dependencies: ["ImagerKit", "ImagerMac"]),
        .testTarget(name: "ImagerKitTests", dependencies: ["ImagerKit"], resources: [.copy("Fixtures")]),
        .testTarget(name: "SofaBoxImagerTests", dependencies: ["SofaBoxImager", "ImagerKit", "ImagerMac"]),
        // Tests only: a stand-in for authopen, so the descriptor hand-over is tested without a password.
        .executableTarget(name: "FakeAuthOpen", path: "Tests/FakeAuthOpen"),
        .testTarget(name: "ImagerMacTests", dependencies: ["ImagerKit", "ImagerMac", "CAuthOpen", "FakeAuthOpen"]),
    ]
)
