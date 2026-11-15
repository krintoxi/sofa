// swift-tools-version:5.9
// Sofa Box Imager: EdgeVenture's own app for writing disks: Sofa Box OS, other Linux systems, Windows installers and
// images of your own, to SD cards, USB sticks and DVDs. The app is macOS 13 or newer; the shared core also builds on
// Windows and Linux.
import PackageDescription

// On Windows and Linux only the shared core and its tests are built for now: the disk side and the window there are
// still to come (see README, "On Windows and Linux").
#if os(macOS)
let targets: [Target] = [
    // Spawns /usr/libexec/authopen and receives the disk's file descriptor from it (C: SCM_RIGHTS needs the CMSG macros).
    .target(name: "CAuthOpen"),
    // Pure Swift, no disks: the lists, which disks may be written (DiskPolicy), the xz unpacker, the write-and-verify
    // engine, and the Windows stick (UDF and WIM readers, the WIM splitter, FAT32, the boot code).
    .target(name: "ImagerKit"),
    // macOS: DiskArbitration and IOKit (finding, unmounting and ejecting disks), authopen, keeping the Mac awake;
    // DiscRecording (the DVD burners) and hdiutil (burning).
    .target(name: "ImagerMac", dependencies: ["ImagerKit", "CAuthOpen"],
            linkerSettings: [.linkedFramework("DiskArbitration"), .linkedFramework("IOKit"),
                             .linkedFramework("Security"), .linkedFramework("DiscRecording")]),
    .executableTarget(name: "SofaBoxImager", dependencies: ["ImagerKit", "ImagerMac"]),
    .testTarget(name: "ImagerKitTests", dependencies: ["ImagerKit"], resources: [.copy("Fixtures")]),
    .testTarget(name: "SofaBoxImagerTests", dependencies: ["SofaBoxImager", "ImagerKit", "ImagerMac"]),
    // Tests only: a stand-in for authopen, so the descriptor hand-over is tested without a password.
    .executableTarget(name: "FakeAuthOpen", path: "Tests/FakeAuthOpen"),
    .testTarget(name: "ImagerMacTests", dependencies: ["ImagerKit", "ImagerMac", "CAuthOpen", "FakeAuthOpen"]),
]
let products: [Product] = [.executable(name: "SofaBoxImager", targets: ["SofaBoxImager"])]
#else
let targets: [Target] = [
    .target(name: "ImagerKit"),
    .testTarget(name: "ImagerKitTests", dependencies: ["ImagerKit"], resources: [.copy("Fixtures")]),
]
let products: [Product] = [.library(name: "ImagerKit", targets: ["ImagerKit"])]
#endif

let package = Package(
    name: "SofaBoxImager",
    platforms: [.macOS(.v13)],
    products: products,
    targets: targets
)
