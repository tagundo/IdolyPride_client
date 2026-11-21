#ifndef IDOLY_OCTO_BUDGET_H
#define IDOLY_OCTO_BUDGET_H

#import <Foundation/Foundation.h>

// Prepare performs only native image/export checks. Configure belongs directly
// after the original Unity initializer returns, on the same main-thread turn.
BOOL IDOctoBudgetPrepare(NSString **error);
BOOL IDOctoBudgetConfigure(BOOL unifiedLoopbackAttested, NSString **error);
NSDictionary *IDOctoBudgetInfo(void);
NSString *IDOctoBudgetLastDiagnostic(void);

#if IDOLY_SMOKE_SIMULATOR
#include "OctoBudgetPolicy.h"
// Explicit fixture injection exists only in the simulator smoke framework.
// The complete table can be registered once, on main, before Prepare.
__attribute__((visibility("default")))
BOOL IDOctoBudgetRegisterSmokeAPIs(const IDOctoBudgetAPIs *apis);
#endif

#endif
