       IDENTIFICATION DIVISION.
       PROGRAM-ID. FINDMAX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY MAXDATA.
       01 RESULT-MSG PIC X(15).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "1020" TO RAW-INPUT.
           PERFORM COMPARE-PARA.
           DISPLAY RESULT-MSG.
           STOP RUN.
       COMPARE-PARA.
           IF NUM1 > NUM2
               MOVE NUM1 TO MAX-NUM
               MOVE "NUM1 MAX" TO RESULT-MSG
           ELSE
               MOVE NUM2 TO MAX-NUM
               MOVE "NUM2 MAX" TO RESULT-MSG
           END-IF.
           DISPLAY "MAX IS: " MAX-NUM.
