       IDENTIFICATION DIVISION.
       PROGRAM-ID. TAX-CALC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 BINARY-DATA  PIC 9(4).
       01 CHAR-DATA    REDEFINES BINARY-DATA PIC X(4).
       01 AMOUNT       PIC 9(7)V99.
       01 TAX-RATE     PIC 9(2)V99.
       01 TAX-AMOUNT   PIC 9(7)V99.
       01 TAX-CLASS    PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1234 TO BINARY-DATA.
           MOVE 1000.00 TO AMOUNT.
           EVALUATE TAX-CLASS
               WHEN 1
                   MOVE 0.10 TO TAX-RATE
               WHEN 2
                   MOVE 0.20 TO TAX-RATE
               WHEN OTHER
                   MOVE 0.05 TO TAX-RATE
           END-EVALUATE.
           COMPUTE TAX-AMOUNT = AMOUNT * TAX-RATE.
           DISPLAY TAX-AMOUNT.
           STOP RUN.
