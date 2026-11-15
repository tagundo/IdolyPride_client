#ifndef IDOLY_OCTO_BUDGET_H
#define IDOLY_OCTO_BUDGET_H

#import <Foundation/Foundation.h>

// Prepare performs only native image/export checks. Configure belongs directly
// after the original Unity initializer returns, on the same main-thread turn.
BOOL IDOctoBudgetPrepare(NSString **error);
BOOL IDOctoBudgetConfigure(BOOL unifiedLoopbackAttested, NSString **error);
NSDictionary *IDOctoBudgetInfo(void);
NSString *IDOctoBudgetLastDiagnostic(void);

#endif
