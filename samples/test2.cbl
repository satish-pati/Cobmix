       IDENTIFICATION DIVISION.
       PROGRAM-ID. GRADE-REPORT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 SCORE    PIC 9(3).
       01 GRADE    PIC X.
       01 STATUS   PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 75 TO SCORE.
           PERFORM CHECK-GRADE.
           PERFORM REPORT-PARA.
           STOP RUN.
       CHECK-GRADE.
           IF SCORE >= 90
               MOVE "A" TO GRADE
           ELSE
               IF SCORE >= 80
                   MOVE "B" TO GRADE
               ELSE
                   IF SCORE >= 70
                       MOVE "C" TO GRADE
                   ELSE
                       MOVE "F" TO GRADE
                   END-IF
               END-IF
           END-IF.
       REPORT-PARA.
           IF GRADE = "A"
               MOVE "PASS" TO STATUS
           ELSE
               MOVE "FAIL" TO STATUS
           END-IF.
           DISPLAY STATUS.
