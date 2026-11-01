#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <stdio.h>
#import "Utils/YTLUserDefaults.h"

static BOOL YTLBackgroundPlaybackEnabled(void) {
    return [[YTLUserDefaults standardUserDefaults] boolForKey:@"backgroundPlayback"];
}

// Keep the existing video-level hooks for older playback paths.
%hook YTIPlayabilityStatus
- (BOOL)isPlayableInBackground { return YTLBackgroundPlaybackEnabled() ? YES : %orig; }
%end

%hook MLVideo
- (BOOL)playableInBackground { return YTLBackgroundPlaybackEnabled() ? YES : %orig; }
%end

%group BackgroundPlaybackData
%hook YTPlaybackData
// This wrapper feeds both the local player and PiP's cached audio prohibition.
- (BOOL)isPlayableInBackground { return YTLBackgroundPlaybackEnabled() ? YES : %orig; }
%end
%end

%group BackgroundPlaybackState
%hook YTSingleVideoController
// The policy getter is insufficient when _backgroundingForcedDisabled is set.
// Let the original setter recompute the cached state and notify observers.
- (void)setBackgroundingForcedDisabled:(BOOL)disabled {
    %orig(YTLBackgroundPlaybackEnabled() ? NO : disabled);
}
%end
%end

%group BackgroundPlaybackPolicy

%hook YTBackgroundabilityPolicy
// YouTube 21.43.5 checks this policy in updateCurrentlyBackgroundable before
// consulting the video's playability. Keep the native state updates and
// observer notifications so background tasks and lock-screen controls agree.
- (BOOL)isBackgroundableByUserSettings {
    return YTLBackgroundPlaybackEnabled() ? YES : %orig;
}
%end

%end

%group PiPBackgroundAudioPolicy
%hook MLPIPController
// AVKit asks this separately when the PiP window goes into the background.
- (BOOL)pictureInPictureControllerShouldProhibitBackgroundAudioPlayback:(id)controller {
    return YTLBackgroundPlaybackEnabled() ? NO : %orig;
}
%end
%end

%group PiPBackgroundAudioState
%hook MLPIPController
- (void)setProhibitsBackgroundAudioPlayback:(BOOL)prohibits {
    %orig(YTLBackgroundPlaybackEnabled() ? NO : prohibits);
}
%end
%end

%ctor {
    %init;

    // Newer YouTube versions moved the policy implementation to an Impl class.
    Class policyClass = objc_getClass("YTBackgroundabilityPolicyImpl") ?: objc_getClass("YTBackgroundabilityPolicy");
    if (policyClass && class_getInstanceMethod(policyClass, @selector(isBackgroundableByUserSettings))) {
        %init(BackgroundPlaybackPolicy, YTBackgroundabilityPolicy = policyClass);
    }

    Class playbackDataClass = objc_getClass("YTPlaybackData");
    if (playbackDataClass && class_getInstanceMethod(playbackDataClass, @selector(isPlayableInBackground))) {
        %init(BackgroundPlaybackData);
    }
    Class singleVideoClass = objc_getClass("YTSingleVideoController");
    if (singleVideoClass && class_getInstanceMethod(singleVideoClass, @selector(setBackgroundingForcedDisabled:))) {
        %init(BackgroundPlaybackState);
    }

    Class pipClass = objc_getClass("MLPIPControllerImpl") ?: objc_getClass("MLPIPController");
    if (pipClass && class_getInstanceMethod(pipClass, @selector(pictureInPictureControllerShouldProhibitBackgroundAudioPlayback:))) {
        %init(PiPBackgroundAudioPolicy, MLPIPController = pipClass);
    }
    if (pipClass && class_getInstanceMethod(pipClass, @selector(setProhibitsBackgroundAudioPlayback:))) {
        %init(PiPBackgroundAudioState, MLPIPController = pipClass);
    }

    // One startup message distinguishes an installed v2 patch from a build
    // that only downloaded the published YTLite binary.
    fprintf(stderr, "[YTLBackgroundPlaybackFix] v2 loaded; policy=%s, PiP=%s\n",
            policyClass ? class_getName(policyClass) : "unavailable",
            pipClass ? class_getName(pipClass) : "unavailable");
}
