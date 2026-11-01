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

Already patched input IPAs are supported when the replaced dependencies are in the unreferenced tail of the load-command table. Before Cyan runs, a staged copy removes old patch/YTLite imports and duplicate library imports. The preparer checks chained imports and undefined symbols first, rejects removals that would renumber any live binding, and preserves all section/file offsets. It never substitutes duplicate system libraries: that caused the earlier `DYLD: duplicate linked dylib '/usr/lib/libz.1.dylib'` launch failure. Legacy binding streams require a clean original IPA. The input IPA is unchanged.

Before release creation, `verify-background-playback.py` checks that the final IPA loads the patch exactly once, contains the v2 guards, matches the compiled patch's machine code, includes its dependencies, and has the audio background mode. To run this check locally:

```sh
python3 scripts/verify-background-playback.py output.ipa --patch packages/YTLBackgroundPlaybackFix.dylib
```

The v2 patch prints `[YTLBackgroundPlaybackFix] v2 loaded` once at process startup so a device console can confirm which build is installed. The pipeline was also exercised locally with Cyan against the supplied app and the compiled v2 patch; a GitHub-hosted run still requires pushing these changes.

On the phone, enable **Background Playback**, start audio, lock for several minutes, and check lock-screen pause/resume and advancement to the next video. Also check unlocking, switching apps, headphones, and a phone-call interruption. Device playback remains a required manual check; the host tests and binary inspection cannot establish that result.

## Account removal from the current release

The latest public [upstream release is 5.2.2](https://github.com/dayanch96/YTLite/releases/tag/v5.2.2). Its executable code matches the newer-labelled tweak supplied with YouTube 21.43.5 (`__TEXT,__text` SHA-256 `73fabfb984369100e7785d3dc5e726140d0f973f0cc31d66632d12d91ad717c2`). The published source tree does not contain this account client's source, so changing `Settings.x` alone cannot remove it from a downloaded release.

`scripts/remove-account.py` verifies the current binary's code, branch data, and obfuscated string data against `scripts/accountless-profile.json`. It then erases the reviewed account function bodies in place. It does not download or bundle 5.2b4. Important paths are:

| Current binary address | Change |
| --- | --- |
| `0x233e8` | Schedule tweak initialization blocks on the main queue directly, without waiting for remote account verification. This includes the current SponsorBlock/player hooks. |
| `0x23680`, `0x2368c`, `0x239c8` | Remove account/lock/device gates; local feature availability no longer consults credentials or keychain. |
| `0x238c0`, `0x23a5c` | Preserve the original bool/integer preference readers and their ARC behavior. Both enabled and disabled values are respected. |
| `0x23ef0`, `0x23b64`, `0x264c4` | Erase exported login, logout, and device management implementations. |
| Account client through `0x3120c`, excluding the preference readers | Erase internal keychain/device ID, token exchange, verification, curl, constructor and callback routines. Their entire bodies become side-effect-free return stubs. |
| `0x37ed4`, `0x37f20` | Disable the automatic activation/guard reminder. |
| `0x17aa28`, `0x191f84` | Remove developer-service donation/supporter requests. |

`Accountless.x` removes the lazy `patreonCell` section before display/search. It installs a rejecting URL protocol for `dvntm.com` and every subdomain, including `api.dvntm.com`, plus WebKit and external-link guards. Account requests cannot escape through the bundled curl client: that client's account callers are erased before the app can launch. YouTube/Google and the public SponsorBlock endpoint remain usable. Dormant account strings and metadata may remain in the binary; they are not a live account integration.

All build workflows sanitize the downloaded current DEB, compile the mandatory `YTLAccountless.dylib`, and package a receipt pinning the transformed code. `scripts/inject-tweaks.sh` verifies the DEB before injection and verifies the final IPA afterward. A missing patch, unsanitized/unknown client, modified code, missing dependency, duplicate library, or receipt mismatch stops the build. The exporter workflows carry the same sanitized client and companion dylib. An unsupported future release needs a reviewed profile; there is no silent downgrade or account-enabled fallback.

Validation commands on macOS:

```sh
LOGOS=/absolute/path/to/logos.pl tests/run-accountless.sh
YTPLUS_TEST_DEB=/path/to/original-current.deb python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m venv /tmp/ytlite-native-check
/tmp/ytlite-native-check/bin/python -m pip install unicorn==2.1.4
/tmp/ytlite-native-check/bin/python tests/check-native-accountless.py /path/to/original-current.deb
python3 scripts/verify-accountless.py output.ipa --patch packages/YTLAccountless.dylib
```

The native regression test emulates the actual transformed arm64 functions with mocked imports. Every erased account routine must return without external calls; local bool/integer preference values must survive; and hook initialization must dispatch the original block to the main queue. The Foundation tests compile the real Logos source, exercise URLSession error completions, hide the account section, and check Google/SponsorBlock URL passthrough. Playback and bedtime regressions run separately. The final verifier checks all arm64 images for duplicate dependencies.

These checks do not establish iPhone launch, playback, or packet-level network behavior. The generated IPA requires device signing. Device launch and a network capture remain the final runtime checks; the verification report records them as untested.
