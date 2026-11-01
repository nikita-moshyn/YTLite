#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <assert.h>
#import "substrate.h"

static NSUInteger presented;
static NSUInteger hooks;

#if REMINDER_VARIANT != 0
@interface YTBedtimeReminderTriggerController : NSObject
- (BOOL)isBedtimeReminderAllowedToTrigger;
- (BOOL)canDisplayBedtimeWarning;
@end
@implementation YTBedtimeReminderTriggerController
- (BOOL)isBedtimeReminderAllowedToTrigger { return YES; }
- (BOOL)canDisplayBedtimeWarning { return YES; }
@end

@interface YTBedtimeReminderController : NSObject
- (void)bedtimeWarningDidFire;
- (void)showBedtimeReminder;
- (void)showBedtimeReminderPanel;
- (void)showBedtimeReminderPanelWithPanelCommand:(id)command;
@end
@implementation YTBedtimeReminderController
- (void)bedtimeWarningDidFire { presented++; }
- (void)showBedtimeReminder { presented++; }
- (void)showBedtimeReminderPanel { presented++; }
- (void)showBedtimeReminderPanelWithPanelCommand:(id)command { (void)command; presented++; }
@end

#if REMINDER_VARIANT == 1
#define REMINDERS_CLASS YTRemindersController
#else
#define REMINDERS_CLASS YTRemindersControllerImpl
#endif
@interface REMINDERS_CLASS : NSObject
- (void)showReminder:(NSInteger)type withPanelCommand:(id)command completionBlock:(id)completion;
@end
@implementation REMINDERS_CLASS
- (void)showReminder:(NSInteger)type withPanelCommand:(id)command completionBlock:(id)completion {
    (void)type;
    assert(command);
    presented++;
    if (completion) ((void (^)(void))completion)();
}
@end
#endif

void MSHookMessageEx(Class cls, SEL selector, IMP replacement, IMP *original) {
    assert(cls);
    Method method = class_getInstanceMethod(cls, selector);
    assert(method);
    *original = method_getImplementation(method);
    class_replaceMethod(cls, selector, replacement, method_getTypeEncoding(method));
    hooks++;
}

int main(void) {
    @autoreleasepool {
#if REMINDER_VARIANT != 0
        assert(hooks == 7);
        YTBedtimeReminderTriggerController *trigger = [YTBedtimeReminderTriggerController new];
        assert(![trigger isBedtimeReminderAllowedToTrigger]);
        assert(![trigger canDisplayBedtimeWarning]);
        YTBedtimeReminderController *bedtime = [YTBedtimeReminderController new];
        [bedtime bedtimeWarningDidFire];
        [bedtime showBedtimeReminder];
        [bedtime showBedtimeReminderPanel];
        [bedtime showBedtimeReminderPanelWithPanelCommand:[NSObject new]];
        REMINDERS_CLASS *dispatcher = [REMINDERS_CLASS new];
        __block NSUInteger completions = 0;
        void (^completion)(void) = ^{ completions++; };
        [dispatcher showReminder:1 withPanelCommand:[NSObject new] completionBlock:completion];
        assert(presented == 0 && completions == 0);
        // The shared dispatcher still handles other reminder types normally.
        [dispatcher showReminder:0 withPanelCommand:[NSObject new] completionBlock:completion];
        [dispatcher showReminder:2 withPanelCommand:[NSObject new] completionBlock:completion];
        assert(presented == 2 && completions == 2);
#else
        assert(hooks == 0);
        assert(presented == 0);
#endif
        printf("PASS: bedtime reminder variant %d\n", REMINDER_VARIANT);
    }
}
