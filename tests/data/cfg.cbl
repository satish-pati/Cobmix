       IDENTIFICATION DIVISION.
       PROGRAM-ID. CFG-DEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
           IF WS-FLAG = 0
              PERFORM INIT-PARA
           ELSE
              PERFORM OTHER-PARA
           END-IF
           PERFORM WORK-PARA THRU END-PARA
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
