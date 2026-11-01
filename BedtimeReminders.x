#import <Foundation/Foundation.h>
#import <objc/runtime.h>

// Always suppress bedtime reminders, independently of playback preferences.
%group BedtimeReminderTriggers
%hook YTBedtimeReminderTriggerController
- (BOOL)isBedtimeReminderAllowedToTrigger { return NO; }
- (BOOL)canDisplayBedtimeWarning { return NO; }
%end
%end

%group BedtimeReminderPresentation
%hook YTBedtimeReminderController
// Also block queued callbacks and the legacy/native panel presentation paths.
- (void)bedtimeWarningDidFire {}
- (void)showBedtimeReminder {}
- (void)showBedtimeReminderPanel {}
- (void)showBedtimeReminderPanelWithPanelCommand:(id)command { (void)command; }
%end
%end

%group BedtimeReminderDispatcher
%hook YTRemindersController
- (void)showReminder:(NSInteger)type withPanelCommand:(id)command completionBlock:(id)completion {
    // In YouTube 21.43.5, reminder type 1 is bedtime. Stop it before the
    // dispatcher notifies observers, pauses playback, or presents the modal.
    if (type != 1) %orig;
}
%end
%end

%ctor {
    if (objc_getClass("YTBedtimeReminderTriggerController")) {
        %init(BedtimeReminderTriggers);
    }
    if (objc_getClass("YTBedtimeReminderController")) {
        %init(BedtimeReminderPresentation);
    }
    Class remindersClass = objc_getClass("YTRemindersControllerImpl") ?: objc_getClass("YTRemindersController");
    if (remindersClass && class_getInstanceMethod(remindersClass, @selector(showReminder:withPanelCommand:completionBlock:))) {
        %init(BedtimeReminderDispatcher, YTRemindersController = remindersClass);
    }
}
