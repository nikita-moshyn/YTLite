#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <assert.h>
#import "substrate.h"

extern BOOL YTLAccountServiceURL(NSURL *url);
static NSUInteger webRequests, externalRequests;
@interface TestSection : NSObject
@property NSString *identifier;
@end
@implementation TestSection
@end
@interface TestModel : NSObject
@property NSArray *sections;
@end
@implementation TestModel
@end
@interface YTPSettingsBuilder : NSObject
- (TestModel *)rootTable;
@end
@implementation YTPSettingsBuilder
- (TestModel *)rootTable {
    TestModel *model = [TestModel new];
    NSMutableArray *sections = [NSMutableArray array];
    for (NSString *identifier in @[@"player", @"patreonCell", @"sponsorblock"]) {
        TestSection *section = [TestSection new];
        section.identifier = identifier;
        [sections addObject:section];
    }
    model.sections = sections;
    return model;
}
@end
@interface WKWebView : NSObject
- (id)loadRequest:(NSURLRequest *)request;
@end
@implementation WKWebView
- (id)loadRequest:(NSURLRequest *)request { (void)request; webRequests++; return @YES; }
@end
@interface UIApplication : NSObject
- (BOOL)openURL:(NSURL *)url;
- (void)openURL:(NSURL *)url options:(id)options completionHandler:(void (^)(BOOL))completion;
@end
@implementation UIApplication
- (BOOL)openURL:(NSURL *)url { (void)url; externalRequests++; return YES; }
- (void)openURL:(NSURL *)url options:(id)options completionHandler:(void (^)(BOOL))completion {
    (void)url; (void)options; externalRequests++; if (completion) completion(YES);
}
@end

void MSHookMessageEx(Class cls, SEL selector, IMP replacement, IMP *original) {
    Method method = class_getInstanceMethod(cls, selector);
    assert(method);
    *original = method_getImplementation(method);
    class_replaceMethod(cls, selector, replacement, method_getTypeEncoding(method));
}

int main(void) {
    @autoreleasepool {
        for (NSString *url in @[@"https://dvntm.com/api/account/login", @"https://API.DVNTM.COM/api/account-verify",
                               @"https://other.dvntm.com/", @"https://dvntm.com./"]) {
            assert(YTLAccountServiceURL([NSURL URLWithString:url]));
        }
        for (NSString *url in @[@"https://accounts.google.com", @"https://youtube.com", @"https://sponsor.ajay.app/api/skipSegments",
                               @"https://notdvntm.com", @"https://dvntm.com.example.org", @"file:///tmp/test"]) {
            assert(!YTLAccountServiceURL([NSURL URLWithString:url]));
        }
        assert(!YTLAccountServiceURL(nil));
        TestModel *model = [[YTPSettingsBuilder new] rootTable];
        assert(model.sections.count == 2);
        assert([[[model.sections firstObject] identifier] isEqualToString:@"player"]);
        assert([[[model.sections lastObject] identifier] isEqualToString:@"sponsorblock"]);
        NSURLRequest *blocked = [NSURLRequest requestWithURL:[NSURL URLWithString:@"https://api.dvntm.com/api/account-verify"]];
        NSURLRequest *allowed = [NSURLRequest requestWithURL:[NSURL URLWithString:@"https://accounts.google.com"]];
        WKWebView *web = [WKWebView new];
        assert(![web loadRequest:blocked] && webRequests == 0);
        assert([web loadRequest:allowed] && webRequests == 1);
        UIApplication *application = [UIApplication new];
        assert(![application openURL:blocked.URL] && externalRequests == 0);
        __block NSUInteger completions = 0;
        [application openURL:blocked.URL options:@{} completionHandler:^(BOOL success) { assert(!success); completions++; }];
        assert(completions == 1 && externalRequests == 0);
        assert([application openURL:allowed.URL] && externalRequests == 1);

        // Exercise a real Foundation URLSession. Its denial protocol returns
        // an error without creating a transport; allowed URLs are never sent.
        for (NSURLSessionConfiguration *configuration in @[[NSURLSessionConfiguration defaultSessionConfiguration],
                                                           [NSURLSessionConfiguration ephemeralSessionConfiguration]]) {
            assert([configuration.protocolClasses containsObject:NSClassFromString(@"YTLAccountServiceProtocol")]);
            NSURLSession *session = [NSURLSession sessionWithConfiguration:configuration];
            dispatch_semaphore_t done = dispatch_semaphore_create(0);
            __block NSError *receivedError;
            [[session dataTaskWithRequest:blocked completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
                assert(!data && !response);
                receivedError = error;
                dispatch_semaphore_signal(done);
            }] resume];
            assert(dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC)) == 0);
            assert(receivedError.code == NSURLErrorNotConnectedToInternet);
            assert([receivedError.localizedDescription containsString:@"account services are disabled"]);
            [session invalidateAndCancel];
        }
        puts("PASS: account UI removal, service URL denial, Google/SponsorBlock passthrough, URLSession error completion");
    }
    return 0;
}
