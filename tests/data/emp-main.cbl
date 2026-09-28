       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMP-MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMPREC.
       01  WS-DATE.
           05  WS-YEAR      PIC 9(4).
           05  WS-MONTH     PIC 9(2).
           05  WS-DAY       PIC 9(2).
       01  WS-DATE-ALPHA REDEFINES WS-DATE PIC X(8).
       01  WS-FLAG          PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
           IF WS-FLAG = 0
              PERFORM INIT-PARA
           ELSE
              PERFORM OTHER-PARA
           END-IF
           PERFORM WORK-PARA THRU END-PARA
           MOVE 1 TO EMP-ID
           GO TO EXIT-PARA.
       INIT-PARA.
           MOVE 1 TO WS-FLAG.
       OTHER-PARA.
           MOVE 2 TO WS-FLAG.
       WORK-PARA.
           ADD 1 TO WS-FLAG.
       END-PARA.
           DISPLAY WS-FLAG.
       EXIT-PARA.
           STOP RUN.
