The background playback regression was investigated against the decrypted YouTube 21.43.5 executable supplied in `Payload 4`, with YTLite 5.3.0. Its app plist already includes the `audio` background mode.

The binary has several separate checks; changing only the user-settings policy does not cover the two screen-lock paths:

| Binary location | Check and effect |
| --- | --- |
| `YTPlaybackData.isPlayableInBackground`, `0x10439af60` | Wrapper consumed by the local player and PiP, in addition to the existing video-level hooks. |
| `YTSingleVideoController.updateCurrentlyBackgroundable`, `0x1040ed370` | A forced-disable flag takes precedence over the user-settings policy. The result is cached. |
| `YTLocalPlaybackController.maybeStopBackgroundPlayback`, `0x1040dad2c` | Rejects non-backgroundable playback; `stopBackgroundPlayback` pauses with reason 15 and releases the audio session. The same backgroundability decision controls lock-screen player availability. |
| `YTPlayerPIPController.setActiveSingleVideo:`, `0x104101a4c` | Caches the inverse of the playback-data backgroundability in `setProhibitsBackgroundAudioPlayback:`. |
| `MLPIPControllerImpl.pictureInPictureControllerShouldProhibitBackgroundAudioPlayback:`, `0x100ef98c0` | Returns that separate cached prohibition to AVKit, including when PiP goes into the background. |

The [AVKit delegate contract](https://developer.apple.com/documentation/avkit/avpictureinpicturesamplebufferplaybackdelegate/pictureinpicturecontrollershouldprohibitbackgroundaudioplayback(_:)) confirms the last check can prohibit background audio independently of PiP eligibility.

`BackgroundPlayback.x` v2 covers the playback-data wrapper, policy, forced-disable setter, and PiP prohibition setter/delegate when the existing `backgroundPlayback` preference is enabled. Original setters still run to recompute state and notify observers. It supports legacy and `Impl` class names and skips unavailable methods. When disabled, original getter results and setter arguments pass through. The native player continues to manage actual pauses, interruptions, background-task expiration, audio sessions, and lock-screen controls.

On macOS with Xcode and Theos/Logos installed, run:

```sh
tests/run-background-playback.sh
python3 -m unittest discover -s tests -p 'test_*.py'
scripts/build-background-playback-fix.sh
```

Set `THEOS` to your Theos directory, or set `LOGOS` to the absolute path of `logos.pl`. The five native test variants compile the actual Logos source and use a runtime hook shim. They cover preference changes, original behavior, both policy/PiP class names, missing methods, and host models of locking directly in-app and locking after PiP with stale prohibitions. Python tests cover file selection, optional downloads, and rejecting missing/stale patches or dependencies. These are host tests, not iOS/AVKit or Substrate integration tests.

The standalone build produces `packages/YTLBackgroundPlaybackFix.dylib` for injection alongside the existing YTLite and CydiaSubstrate libraries. It uses the installed YTLite preferences class. A normal Theos source build includes `BackgroundPlayback.x` automatically.

In **Create YouTube Plus app** (`main.yml`), leave **Build and inject the screen-lock/background audio fix from this branch** enabled (the default). Run the workflow from the branch containing these changes. The helper checks out that branch, tests/builds the patch with pinned Logos, and includes the `.dylib` in the artifact. Packaging injects `.deb` and `.dylib` files once each and ensures `UIBackgroundModes` includes `audio`.

The optional `extra_tweaks_urls` input accepts direct `.deb` or `.dylib` download URLs separated by spaces/newlines. Downloads are validated from their contents, extensionless download URLs are supported, and filenames with spaces are preserved. GitHub's workflow form does not upload local files; host additional binaries at direct URLs. The background patch itself is built automatically from source and needs no extra URL.

Already patched input IPAs are supported. Before Cyan runs, a staged copy drops the previous patch file and retargets its old dependency commands to the already loaded system library. This preserves existing dylib binding ordinals and file offsets while allowing Cyan to add the replacement exactly once. The input IPA is unchanged.

Before release creation, `verify-background-playback.py` checks that the final IPA loads the patch exactly once, contains the v2 guards, matches the compiled patch's machine code, includes its dependencies, and has the audio background mode. To run this check locally:

```sh
python3 scripts/verify-background-playback.py output.ipa --patch packages/YTLBackgroundPlaybackFix.dylib
```

The v2 patch prints `[YTLBackgroundPlaybackFix] v2 loaded` once at process startup so a device console can confirm which build is installed. The pipeline was also exercised locally with Cyan against the supplied app and the compiled v2 patch; a GitHub-hosted run still requires pushing these changes.

On the phone, enable **Background Playback**, start audio, lock for several minutes, and check lock-screen pause/resume and advancement to the next video. Also check unlocking, switching apps, headphones, and a phone-call interruption. Device playback remains a required manual check; the host tests and binary inspection cannot establish that result.
