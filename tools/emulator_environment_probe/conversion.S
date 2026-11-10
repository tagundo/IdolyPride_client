.text
.p2align 2
.global probe_fcvtzs
.type probe_fcvtzs,%function
probe_fcvtzs:
    fmov s1, s0
    .inst 0x5ea1b821 // Exact crashing game opcode: FCVTZS S1,S1.
    .inst 0x5e21d821 // SCVTF S1,S1, convert integer bits back to float.
    fmov s0, s1
    ret
.size probe_fcvtzs, .-probe_fcvtzs
.section .note.GNU-stack,"",%progbits
