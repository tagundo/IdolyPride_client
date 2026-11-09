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

.global idoly_machine_checkpoint_add
.hidden idoly_machine_checkpoint_add
.type idoly_machine_checkpoint_add, %function
idoly_machine_checkpoint_add:
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
.global idoly_machine_instruction_add
.hidden idoly_machine_instruction_add
.type idoly_machine_instruction_add, %function
idoly_machine_instruction_add:
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
.size idoly_machine_checkpoint_add, .-idoly_machine_checkpoint_add

// Ordinary replay cases include the exact stack/LR instruction shapes used
// by the profile. Each wrapper owns its scratch memory and restores the caller.
.macro ORDINARY_CHECKPOINT name, word, mode
.p2align 4
.global idoly_machine_checkpoint_\name
.hidden idoly_machine_checkpoint_\name
.type idoly_machine_checkpoint_\name, %function
idoly_machine_checkpoint_\name:
    stp x29, x30, [sp, #-320]!
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
.if \mode == 6
    // Distinct initial memory on every run; SP and stored LR are both checked.
    sub sp, sp, #16
    str xzr, [sp]
    add sp, sp, #16
.endif
.if \mode == 7
    sub sp, sp, #16
    mov x16, #0x9001
    mov x17, #0x9002
    stp x16, x17, [sp]
.endif
    movi v0.16b, #1
    movi v1.16b, #2
    movi v2.16b, #3
    movi v3.16b, #4
    movi v4.16b, #5
    movi v5.16b, #6
    movi v6.16b, #7
    movi v7.16b, #8
    movi v8.16b, #9
    movi v9.16b, #10
    movi v10.16b, #11
    movi v11.16b, #12
    movi v12.16b, #13
    movi v13.16b, #14
    movi v14.16b, #15
    movi v15.16b, #16
    movi v16.16b, #17
    movi v17.16b, #18
    movi v18.16b, #19
    movi v19.16b, #20
    movi v20.16b, #21
    movi v21.16b, #22
    movi v22.16b, #23
    movi v23.16b, #24
    movi v24.16b, #25
    movi v25.16b, #26
    movi v26.16b, #27
    movi v27.16b, #28
    movi v28.16b, #29
    movi v29.16b, #30
    movi v30.16b, #31
    movi v31.16b, #32
    mov x16, #0x400000
    msr fpcr, x16
    mov x16, #0x8000000
    msr fpsr, x16
    mov x16, #0xa0000000
    msr nzcv, x16
.irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,19,20,21,22,23,24,25,26,27,29,30
    mov x\n, #(0x101 + \n)
.endr
.if (\mode == 3) || (\mode == 4)
    add x19, sp, #256
    mov x16, #0x9001
    mov x17, #0x9002
.if \mode == 3
    str x16, [x19, #0x30]
.else
    stp x16, x17, [x19, #0x20]
.endif
    mov x16, #0x111
    mov x17, #0x112
.endif
    SNAPSHOT
.global idoly_machine_instruction_\name
.hidden idoly_machine_instruction_\name
.type idoly_machine_instruction_\name, %function
idoly_machine_instruction_\name:
    .inst \word
    add x28, x28, #800
    SNAPSHOT
.if \mode == 5
    add sp, sp, #0x90
.elseif \mode == 6
    ldr x9, [sp]
    str x9, [x28, #800]
    add sp, sp, #16
.endif
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
    ldp x29, x30, [sp], #320
    ret
.size idoly_machine_checkpoint_\name, .-idoly_machine_checkpoint_\name
.endm

ORDINARY_CHECKPOINT mov, 0xaa0103e0, 2
ORDINARY_CHECKPOINT ldr, 0xf9401a61, 3
ORDINARY_CHECKPOINT ldp, 0xa9420662, 4
ORDINARY_CHECKPOINT subsp, 0xd10243ff, 5
ORDINARY_CHECKPOINT strpre, 0xf81f0ffe, 6
ORDINARY_CHECKPOINT ldppost, 0xa8c14ffe, 7
.section .note.GNU-stack,"",%progbits
