/*
 * Sofa Box Imager's master boot record (the code part, 440 bytes at most; the disk signature, the partition table and
 * 55 AA follow it). Ours, written for the Windows sticks: it starts the active partition, as every MBR since DOS has.
 *
 * The BIOS loads it at 0000:7C00 with the drive in DL. It moves itself to 0000:0600, finds the active partition, reads
 * that partition's first sector to 0000:7C00 by LBA (INT 13h, AH=42h), and jumps there with DL the drive and DS:SI the
 * partition's entry, the convention boot sectors expect.
 *
 * Build (Xcode's own clang; BootCode.swift holds the bytes, and a test checks they're these):
 *   xcrun clang -c -target i386-unknown-none-elf mbr.S -o mbr.o
 */
        .code16
        .text
        .globl  _start
_start:
        cli
        xorw    %ax, %ax
        movw    %ax, %ss
        movw    $0x7c00, %sp
        movw    %ax, %ds
        movw    %ax, %es
        sti
        cld
        movw    $0x7c00, %si
        movw    $0x0600, %di
        movw    $256, %cx
        rep movsw
        ljmp    $0, $(0x600 + moved - _start)
moved:
        movb    %dl, (0x600 + drive - _start)
        movw    $(0x600 + 0x1be), %si
        movw    $4, %cx
1:      testb   $0x80, (%si)
        jnz     found
        addw    $16, %si
        loop    1b
        movw    $(0x600 + msg_active - _start), %si
        jmp     fail
found:
        movw    %si, (0x600 + entry - _start)
        movb    $0x41, %ah                      /* are the LBA calls there? */
        movw    $0x55aa, %bx
        movb    (0x600 + drive - _start), %dl
        int     $0x13
        jc      no_lba
        cmpw    $0xaa55, %bx
        jne     no_lba
        testb   $1, %cl
        jz      no_lba
        movw    (0x600 + entry - _start), %si
        movl    8(%si), %eax                    /* the partition's first sector */
        movl    %eax, (0x600 + dap_lba - _start)
        movw    $(0x600 + dap - _start), %si
        movb    $0x42, %ah
        movb    (0x600 + drive - _start), %dl
        int     $0x13
        jc      read_error
        cmpw    $0xaa55, (0x7dfe)
        jne     no_boot
        movw    (0x600 + entry - _start), %si
        movb    (0x600 + drive - _start), %dl
        ljmp    $0, $0x7c00
no_lba:
        movw    $(0x600 + msg_lba - _start), %si
        jmp     fail
read_error:
        movw    $(0x600 + msg_read - _start), %si
        jmp     fail
no_boot:
        movw    $(0x600 + msg_boot - _start), %si
fail:
        lodsb
        testb   %al, %al
        jz      halt
        movb    $0x0e, %ah
        movw    $7, %bx
        int     $0x10
        jmp     fail
halt:
        hlt
        jmp     halt

drive:  .byte   0x80
entry:  .word   0
dap:    .byte   16, 0
        .word   1                               /* one sector */
        .word   0x7c00, 0                       /* to 0000:7C00 */
dap_lba:
        .long   0, 0
msg_active:
        .asciz  "No active partition"
msg_lba:
        .asciz  "No LBA disk calls"
msg_read:
        .asciz  "Disk read error"
msg_boot:
        .asciz  "No boot sector"
