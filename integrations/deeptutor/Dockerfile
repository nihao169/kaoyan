FROM ghcr.io/hkuds/deeptutor@sha256:4982ca6bf43b98431366b43d1fec674a63656db3fbe49ba18c674bb6f19196dd
COPY patch_kaoyan_questions.py /tmp/patch_kaoyan_questions.py
RUN python /tmp/patch_kaoyan_questions.py /app/deeptutor && rm /tmp/patch_kaoyan_questions.py
