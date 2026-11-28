.text
.global original_prepare
.type original_prepare,%function
original_prepare:
 adrp x9, observed
 add x9, x9, :lo12:observed
 stp x0,x1,[x9]
 stp x2,x3,[x9,#16]
 str x4,[x9,#32]
 ldp q0,q1,[x3]
 add x10,x9,#40
 stp q0,q1,[x10]
 ldp q0,q1,[x3,#32]
 stp q0,q1,[x10,#32]
 b original_sync
.size original_prepare,.-original_prepare
.global original_sync
.type original_sync,%function
original_sync:
 adrp x9, observed
 add x9,x9,:lo12:observed
 str x30,[x9,#104]
 ret
.size original_sync,.-original_sync
