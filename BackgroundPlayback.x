#import <Foundation/Foundation.h>
#import <objc/runtime.h>
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

%ctor {
    %init;

    // Newer YouTube versions moved the policy implementation to an Impl class.
    Class policyClass = objc_getClass("YTBackgroundabilityPolicyImpl") ?: objc_getClass("YTBackgroundabilityPolicy");
    if (policyClass && class_getInstanceMethod(policyClass, @selector(isBackgroundableByUserSettings))) {
        %init(BackgroundPlaybackPolicy, YTBackgroundabilityPolicy = policyClass);
    }
}
