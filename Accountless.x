#import <Foundation/Foundation.h>
#import <objc/runtime.h>

// The native account client (including its bundled curl requests) is removed
// BEFORE injection by scripts/remove-account.py. This layer removes the entry
// in settings and denies the remaining Foundation/WebKit service URLs.
BOOL YTLAccountServiceURL(NSURL *url) {
    NSString *host = url.host.lowercaseString;
    while ([host hasSuffix:@"."]) host = [host substringToIndex:host.length - 1];
    return [host isEqualToString:@"dvntm.com"] || [host hasSuffix:@".dvntm.com"];
}

@interface YTLAccountServiceProtocol : NSURLProtocol
@end
@implementation YTLAccountServiceProtocol
+ (BOOL)canInitWithRequest:(NSURLRequest *)request { return YTLAccountServiceURL(request.URL); }
+ (NSURLRequest *)canonicalRequestForRequest:(NSURLRequest *)request { return request; }
- (void)startLoading {
    NSError *error = [NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorNotConnectedToInternet
        userInfo:@{NSLocalizedDescriptionKey: @"YTPlus account services are disabled in this build."}];
    [self.client URLProtocol:self didFailWithError:error];
}
- (void)stopLoading {}
@end

@interface NSObject (YTLOfflineSettings)
- (NSArray *)sections;
- (void)setSections:(NSArray *)sections;
- (NSString *)identifier;
@end

%group AccountlessSettings
%hook YTPSettingsBuilder
- (id)rootTable {
    id model = %orig;
    // The original factory only constructs the lazy account section; do not
    // evaluate its cellsProvider. Remove it before display or recursive search.
    NSMutableArray *sections = [[model sections] mutableCopy];
    NSIndexSet *account = [sections indexesOfObjectsPassingTest:^BOOL(id section, NSUInteger index, BOOL *stop) {
        (void)index; (void)stop;
        return [[section identifier] isEqualToString:@"patreonCell"];
    }];
    [sections removeObjectsAtIndexes:account];
    [model setSections:sections];
    return model;
}
%end
%end

%hook NSURLSessionConfiguration
- (NSArray *)protocolClasses {
    NSMutableArray *classes = [%orig mutableCopy] ?: [NSMutableArray array];
    [classes removeObject:[YTLAccountServiceProtocol class]];
    [classes insertObject:[YTLAccountServiceProtocol class] atIndex:0];
    return classes;
}
%end

%group AccountlessWebKit
%hook WKWebView
- (id)loadRequest:(NSURLRequest *)request {
    return YTLAccountServiceURL(request.URL) ? nil : %orig;
}
%end
%end

%group AccountlessExternalLinks
%hook UIApplication
- (BOOL)openURL:(NSURL *)url { return YTLAccountServiceURL(url) ? NO : %orig; }
- (void)openURL:(NSURL *)url options:(id)options completionHandler:(void (^)(BOOL))completion {
    if (YTLAccountServiceURL(url)) {
        if (completion) completion(NO);
        return;
    }
    %orig;
}
%end
%end

%ctor {
    [NSURLProtocol registerClass:[YTLAccountServiceProtocol class]];
    %init;
    Class builder = objc_getClass("YTPSettingsBuilder");
    if (class_getInstanceMethod(builder, @selector(rootTable))) %init(AccountlessSettings);
    Class web = objc_getClass("WKWebView");
    if (class_getInstanceMethod(web, @selector(loadRequest:))) %init(AccountlessWebKit);
    Class application = objc_getClass("UIApplication");
    if (class_getInstanceMethod(application, @selector(openURL:options:completionHandler:))) %init(AccountlessExternalLinks);
}
