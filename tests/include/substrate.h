#pragma once
#import <objc/runtime.h>

#ifdef __cplusplus
extern "C" {
#endif
void MSHookMessageEx(Class cls, SEL selector, IMP replacement, IMP *original);
#ifdef __cplusplus
}
#endif
