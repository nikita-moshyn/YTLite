The background playback regression was investigated against the decrypted YouTube 21.43.5 executable supplied in `Payload 4`, with YTLite 5.3.0. Its app plist already includes the `audio` background mode.

In this binary, `YTSingleVideoController.updateCurrentlyBackgroundable` checks `YTBackgroundabilityPolicyImpl.isBackgroundableByUserSettings` before consulting the video's playability. `YTLocalPlaybackController.maybeStopBackgroundPlayback` stops playback when the resulting state is false. The existing video-level hooks alone do not cover the policy check.

`BackgroundPlayback.x` overrides that policy when the existing `backgroundPlayback` preference is enabled. It supports both the concrete `Impl` class and the older class name, skips an unavailable policy method, and preserves the original getter results when the preference is disabled. The native player still manages background tasks, audio sessions, and lock-screen controls.

On macOS with Xcode and Theos/Logos installed, run:

```sh
tests/run-background-playback.sh
scripts/build-background-playback-fix.sh
```

Set `THEOS` to your Theos directory, or set `LOGOS` to the absolute path of `logos.pl`. The tests compile the actual Logos source and use a runtime hook shim. They cover enabled/disabled preferences with both native return values, preference changes, legacy/modern classes, class selection when both exist, and missing classes or methods. They do not exercise iOS audio hardware or the actual Substrate implementation.

The standalone build produces `packages/YTLBackgroundPlaybackFix.dylib` for injection alongside the existing YTLite and CydiaSubstrate libraries. It uses the installed YTLite preferences class. A normal Theos source build includes `BackgroundPlayback.x` automatically; GitHub Actions workflows that download a published YTLite package require the standalone patch to be injected as well.

On the phone, enable **Background Playback**, start audio, lock for several minutes, and check lock-screen pause/resume and advancement to the next video. Also check unlocking, switching apps, headphones, and a phone-call interruption. Device playback remains a required manual check; the host tests and binary inspection cannot establish that result.
