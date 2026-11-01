#import <Foundation/Foundation.h>
#import <objc/message.h>
#import <objc/runtime.h>
#import <assert.h>
#import "Utils/YTLUserDefaults.h"
#import "substrate.h"

static BOOL tweakEnabled;
static BOOL nativeAllowed;
static NSUInteger originalCalls;
static NSUInteger installedHooks;
static NSUInteger stateUpdates;

@protocol BackgroundPolicy
- (BOOL)isBackgroundableByUserSettings;
@end

@implementation YTLUserDefaults
+ (YTLUserDefaults *)standardUserDefaults {
    static YTLUserDefaults *defaults;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        defaults = [[self alloc] initWithSuiteName:@"YTLite.BackgroundPlayback.Tests"];
    });
    return defaults;
}
- (BOOL)boolForKey:(NSString *)key {
    assert([key isEqualToString:@"backgroundPlayback"]);
    return tweakEnabled;
}
- (void)reset {}
+ (void)resetUserDefaults {}
@end

@interface YTIPlayabilityStatus : NSObject
- (BOOL)isPlayableInBackground;
@end
@implementation YTIPlayabilityStatus
- (BOOL)isPlayableInBackground { originalCalls++; return nativeAllowed; }
@end

@interface MLVideo : NSObject
- (BOOL)playableInBackground;
@end
@implementation MLVideo
- (BOOL)playableInBackground { originalCalls++; return nativeAllowed; }
@end

@interface YTPlaybackData : NSObject
- (BOOL)isPlayableInBackground;
@end
@implementation YTPlaybackData
- (BOOL)isPlayableInBackground { originalCalls++; return nativeAllowed; }
@end

@interface YTSingleVideoController : NSObject
@property (nonatomic, strong) YTPlaybackData *playbackData;
@property (nonatomic, strong) id<BackgroundPolicy> policy;
@property (nonatomic) BOOL backgroundingForcedDisabled;
@property (nonatomic) BOOL currentlyBackgroundable;
@end
@implementation YTSingleVideoController
- (void)setBackgroundingForcedDisabled:(BOOL)disabled {
    _backgroundingForcedDisabled = disabled;
    // Model the three checks in 21.43.5's updateCurrentlyBackgroundable.
    self.currentlyBackgroundable = !disabled && [self.policy isBackgroundableByUserSettings]
        && [self.playbackData isPlayableInBackground];
    stateUpdates++;
}
@end

@interface NativePiPAudio : NSObject
@property (nonatomic) BOOL nativeProhibition;
- (BOOL)pictureInPictureControllerShouldProhibitBackgroundAudioPlayback:(id)controller;
@end
@implementation NativePiPAudio
- (BOOL)pictureInPictureControllerShouldProhibitBackgroundAudioPlayback:(id)controller {
    (void)controller;
    originalCalls++;
    return self.nativeProhibition;
}
@end

#if POLICY_VARIANT == 1 || POLICY_VARIANT == 3
@interface MLPIPController : NativePiPAudio
- (void)setProhibitsBackgroundAudioPlayback:(BOOL)prohibits;
@end
@implementation MLPIPController
- (void)setProhibitsBackgroundAudioPlayback:(BOOL)prohibits { self.nativeProhibition = prohibits; }
@end
#endif

#if POLICY_VARIANT >= 2
@interface MLPIPControllerImpl : NativePiPAudio
#if POLICY_VARIANT != 4
- (void)setProhibitsBackgroundAudioPlayback:(BOOL)prohibits;
#endif
@end
@implementation MLPIPControllerImpl
#if POLICY_VARIANT != 4
- (void)setProhibitsBackgroundAudioPlayback:(BOOL)prohibits { self.nativeProhibition = prohibits; }
#endif
@end
#endif

// 0: no policy, 1: legacy, 2: modern, 3: both, 4: selector removed.
#if POLICY_VARIANT == 1 || POLICY_VARIANT == 3
@interface YTBackgroundabilityPolicy : NSObject
- (BOOL)isBackgroundableByUserSettings;
@end
@implementation YTBackgroundabilityPolicy
- (BOOL)isBackgroundableByUserSettings { originalCalls++; return nativeAllowed; }
@end
#endif

#if POLICY_VARIANT >= 2
@interface YTBackgroundabilityPolicyImpl : NSObject
#if POLICY_VARIANT != 4
- (BOOL)isBackgroundableByUserSettings;
#endif
@end
@implementation YTBackgroundabilityPolicyImpl
#if POLICY_VARIANT != 4
- (BOOL)isBackgroundableByUserSettings { originalCalls++; return nativeAllowed; }
#endif
@end
#endif

void MSHookMessageEx(Class cls, SEL selector, IMP replacement, IMP *original) {
    assert(cls);
    Method method = class_getInstanceMethod(cls, selector);
    assert(method);
    *original = method_getImplementation(method);
    class_replaceMethod(cls, selector, replacement, method_getTypeEncoding(method));
    installedHooks++;
}

static void checkPlaybackDecision(id object, SEL selector) {
    BOOL (*invoke)(id, SEL) = (BOOL (*)(id, SEL))objc_msgSend;
    for (NSUInteger enabled = 0; enabled < 2; enabled++) {
        for (NSUInteger allowed = 0; allowed < 2; allowed++) {
            tweakEnabled = enabled;
            nativeAllowed = allowed;
            originalCalls = 0;
            assert(invoke(object, selector) == (enabled || allowed));
            assert(originalCalls == (enabled ? 0 : 1));
        }
    }

    // Read the preference on every call, including after disabling it again.
    tweakEnabled = YES;
    nativeAllowed = NO;
    assert(invoke(object, selector));
    tweakEnabled = NO;
    assert(!invoke(object, selector));
}

#if POLICY_VARIANT >= 1
static void checkPiPDecision(NativePiPAudio *pip) {
    for (NSUInteger enabled = 0; enabled < 2; enabled++) {
        for (NSUInteger prohibits = 0; prohibits < 2; prohibits++) {
            tweakEnabled = enabled;
            pip.nativeProhibition = prohibits; // Include a stale cached prohibition.
            originalCalls = 0;
            assert([pip pictureInPictureControllerShouldProhibitBackgroundAudioPlayback:nil] == (!enabled && prohibits));
            assert(originalCalls == (enabled ? 0 : 1));
            if ([pip respondsToSelector:@selector(setProhibitsBackgroundAudioPlayback:)]) {
                ((void (*)(id, SEL, BOOL))objc_msgSend)(pip, @selector(setProhibitsBackgroundAudioPlayback:), prohibits);
                assert(pip.nativeProhibition == (!enabled && prohibits));
            }
        }
    }
}
#endif

// Host model of the two binary paths; this does not emulate iOS/AVKit hardware.
#if POLICY_VARIANT >= 1 && POLICY_VARIANT <= 3
static void checkLockScenarios(id<BackgroundPolicy> policy, NativePiPAudio *pip) {
    for (NSUInteger startsInPiP = 0; startsInPiP < 2; startsInPiP++) {
        tweakEnabled = YES;
        nativeAllowed = NO;
        YTSingleVideoController *video = [YTSingleVideoController new];
        video.playbackData = [YTPlaybackData new];
        video.policy = policy;
        stateUpdates = 0;
        [video setBackgroundingForcedDisabled:YES];
        assert(!video.backgroundingForcedDisabled);
        assert(video.currentlyBackgroundable);
        assert(stateUpdates == 1); // Native recomputation/notifications still run.

        BOOL playing = YES;
        BOOL lockScreenPlayer = YES;
        // Lock directly in-app, or lock after the PiP window appeared.
        pip.nativeProhibition = YES;
        BOOL stopForPiP = startsInPiP && [pip pictureInPictureControllerShouldProhibitBackgroundAudioPlayback:nil];
        if (!video.currentlyBackgroundable || stopForPiP) {
            playing = NO;
            lockScreenPlayer = NO;
        }
        assert(playing && lockScreenPlayer);
        tweakEnabled = NO;
        nativeAllowed = YES;
        [video setBackgroundingForcedDisabled:YES];
        assert(video.backgroundingForcedDisabled && !video.currentlyBackgroundable);
        [video setBackgroundingForcedDisabled:NO];
        assert(!video.backgroundingForcedDisabled && video.currentlyBackgroundable);
    }
}
#endif

int main(void) {
    @autoreleasepool {
        checkPlaybackDecision([YTIPlayabilityStatus new], @selector(isPlayableInBackground));
        checkPlaybackDecision([MLVideo new], @selector(playableInBackground));
        checkPlaybackDecision([YTPlaybackData new], @selector(isPlayableInBackground));

#if POLICY_VARIANT == 1
        checkPlaybackDecision([YTBackgroundabilityPolicy new], @selector(isBackgroundableByUserSettings));
        checkPiPDecision([MLPIPController new]);
        checkLockScenarios((id)[YTBackgroundabilityPolicy new], [MLPIPController new]);
#elif POLICY_VARIANT == 2 || POLICY_VARIANT == 3
        checkPlaybackDecision([YTBackgroundabilityPolicyImpl new], @selector(isBackgroundableByUserSettings));
        checkPiPDecision([MLPIPControllerImpl new]);
        checkLockScenarios((id)[YTBackgroundabilityPolicyImpl new], [MLPIPControllerImpl new]);
#elif POLICY_VARIANT == 4
        checkPiPDecision([MLPIPControllerImpl new]);
#endif

#if POLICY_VARIANT == 3
        // Prefer the concrete Impl class when both names are present.
        tweakEnabled = YES;
        nativeAllowed = NO;
        assert(![[YTBackgroundabilityPolicy new] isBackgroundableByUserSettings]);
#endif

        assert(installedHooks == ((POLICY_VARIANT >= 1 && POLICY_VARIANT <= 3) ? 7 : (POLICY_VARIANT == 4 ? 5 : 4)));
        printf("PASS: background playback policy variant %d\n", POLICY_VARIANT);
    }
    return 0;
}
