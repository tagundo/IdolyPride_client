// SPDX-License-Identifier: AGPL-3.0-or-later
#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
// Called on the serial native worker before one-shot capture is admitted.
// No original output is moved or deleted by this metadata-only catalog.
FOUNDATION_EXPORT BOOL IDMP4LibraryBookmark(NSString *dataRoot,NSString *exports,NSString * _Nullable * _Nonnull error);
FOUNDATION_EXPORT NSDictionary * _Nullable IDMP4LibraryStatus(NSString *dataRoot,NSArray *queueJobs,
    NSString * _Nullable queueExports,NSUInteger offset,NSString * _Nullable * _Nonnull error);
FOUNDATION_EXPORT NSURL * _Nullable IDMP4LibraryFile(NSString *dataRoot,NSArray *queueJobs,
    NSString * _Nullable queueExports,NSString * _Nullable exportID,NSString * _Nullable * _Nonnull error);
NS_ASSUME_NONNULL_END
