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

int main(void) {
    @autoreleasepool {
        checkPlaybackDecision([YTIPlayabilityStatus new], @selector(isPlayableInBackground));
        checkPlaybackDecision([MLVideo new], @selector(playableInBackground));

#if POLICY_VARIANT == 1
        checkPlaybackDecision([YTBackgroundabilityPolicy new], @selector(isBackgroundableByUserSettings));
#elif POLICY_VARIANT == 2 || POLICY_VARIANT == 3
        checkPlaybackDecision([YTBackgroundabilityPolicyImpl new], @selector(isBackgroundableByUserSettings));
#endif

#if POLICY_VARIANT == 3
        // Prefer the concrete Impl class when both names are present.
        tweakEnabled = YES;
        nativeAllowed = NO;
        assert(![[YTBackgroundabilityPolicy new] isBackgroundableByUserSettings]);
#endif

        assert(installedHooks == ((POLICY_VARIANT >= 1 && POLICY_VARIANT <= 3) ? 3 : 2));
        printf("PASS: background playback policy variant %d\n", POLICY_VARIANT);
    }
    return 0;
}
