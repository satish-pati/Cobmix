       IDENTIFICATION DIVISION.
       PROGRAM-ID. DFG-DEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(2).
       01  WS-B PIC 9(2).
       PROCEDURE DIVISION.
       MAIN.
           MOVE 10 TO WS-A
           COMPUTE WS-B = WS-A + 1
           DISPLAY WS-B
           STOP RUN.
