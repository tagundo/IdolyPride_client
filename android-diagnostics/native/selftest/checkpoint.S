// Synthetic ARM64 fixture only. No game code, addresses or data are involved.
.text
.p2align 4

// Snapshot layout: x0..x30, SP, NZCV, FPCR, FPSR, padding, q0..q31 (800 bytes).
.macro SNAPSHOT
.irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30
    str x\n, [x28, #(\n * 8)]
.endr
    mov x16, sp
    str x16, [x28, #248]
    mrs x16, nzcv
    str x16, [x28, #256]
    mrs x16, fpcr
    str x16, [x28, #264]
    mrs x16, fpsr
    str x16, [x28, #272]
.irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31
    str q\n, [x28, #(288 + \n * 16)]
.endr
    ldr x16, [x28, #128]
.endm

.global idoly_selftest_checkpoint
.type idoly_selftest_checkpoint, %function
idoly_selftest_checkpoint:
    stp x29, x30, [sp, #-256]!
    stp x19, x20, [sp, #16]
    stp x21, x22, [sp, #32]
    stp x23, x24, [sp, #48]
    stp x25, x26, [sp, #64]
    stp x27, x28, [sp, #80]
    stp q8, q9, [sp, #96]
    stp q10, q11, [sp, #128]
    stp q12, q13, [sp, #160]
    stp q14, q15, [sp, #192]
    mrs x9, fpcr
    str x9, [sp, #224]
    mrs x9, fpsr
    str x9, [sp, #232]
    mrs x9, nzcv
    str x9, [sp, #240]
    mov x28, x0
.irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31
    movi v\n\().16b, #(\n + 1)
.endr
    mov x16, #0x400000
    msr fpcr, x16
    mov x16, #0x8000000
    msr fpsr, x16
    mov x16, #0xa0000000
    msr nzcv, x16
    // Android reserves x18; retain its genuine platform value throughout.
.irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,19,20,21,22,23,24,25,26,27,29,30
    mov x\n, #(0x101 + \n)
.endr
    SNAPSHOT
.global idoly_selftest_instruction
.type idoly_selftest_instruction, %function
idoly_selftest_instruction:
    add x0, x0, #7
    // The fixture deliberately advances only its snapshot output pointer.
    add x28, x28, #800
    SNAPSHOT
    ldr x9, [sp, #224]
    msr fpcr, x9
    ldr x9, [sp, #232]
    msr fpsr, x9
    ldr x9, [sp, #240]
    msr nzcv, x9
    ldp q8, q9, [sp, #96]
    ldp q10, q11, [sp, #128]
    ldp q12, q13, [sp, #160]
    ldp q14, q15, [sp, #192]
    ldp x19, x20, [sp, #16]
    ldp x21, x22, [sp, #32]
    ldp x23, x24, [sp, #48]
    ldp x25, x26, [sp, #64]
    ldp x27, x28, [sp, #80]
    ldp x29, x30, [sp], #256
    ret
.size idoly_selftest_checkpoint, .-idoly_selftest_checkpoint
.section .note.GNU-stack,"",%progbits
