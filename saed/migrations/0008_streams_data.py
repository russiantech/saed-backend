"""Data migration: derive streams from existing orientation camps and split accounts into In-Camp / Post-Camp tracks.

Nothing is deleted. Camps that share the same start/end dates become one stream (numbered per year in start order);
legacy "both" accounts become In-Camp only when they were placed in a camp, otherwise Post-Camp.
"""
from django.db import migrations
from django.utils.timezone import now


def forwards(apps, schema_editor):
    Camp = apps.get_model("saed", "OrientationCamp")
    Stream = apps.get_model("saed", "Stream")
    Course = apps.get_model("saed", "Course")
    Profile = apps.get_model("saed", "Profile")
    Membership = apps.get_model("saed", "StreamMembership")
    today = now().date()

    per_year, by_dates = {}, {}
    for camp in Camp.objects.order_by("start_date", "id"):
        key = (camp.start_date, camp.end_date)
        stream = by_dates.get(key)
        if stream is None:
            n = per_year.get(camp.start_date.year, 0) + 1
            per_year[camp.start_date.year] = n
            stream = Stream.objects.create(
                year=camp.start_date.year, number=n, start_date=camp.start_date, end_date=camp.end_date,
                deactivation_grace_days=camp.deactivation_grace_days, is_active=camp.is_active)
            by_dates[key] = stream
        camp.stream = stream
        camp.save(update_fields=["stream"])

    for course in Course.objects.filter(course_type="in_camp", orientation_camp__isnull=False, stream__isnull=True):
        course.stream_id = course.orientation_camp.stream_id
        course.save(update_fields=["stream"])

    def expired(stream):
        from datetime import timedelta
        return today > stream.end_date + timedelta(days=stream.deactivation_grace_days)

    # Corps members
    for p in Profile.objects.filter(role="corps_member"):
        camp = p.orientation_camp
        if camp is not None and camp.stream_id and p.account_mode in ("both", "in_camp"):
            p.account_mode = "in_camp"
            p.save(update_fields=["account_mode"])
            st = camp.stream
            Membership.objects.get_or_create(
                user_id=p.user_id, stream=st,
                defaults={"role": "corps_member",
                          "status": "active" if (p.in_camp_access_active and not expired(st)) else "expired"})
        else:
            p.account_mode = "post_camp"
            p.save(update_fields=["account_mode"])

    # Trainers whose only courses are In-Camp (all inside a stream) become In-Camp trainers
    for p in Profile.objects.filter(role="trainer"):
        courses = list(Course.objects.filter(trainer_id=p.user_id))
        in_camp = [c for c in courses if c.course_type == "in_camp"]
        if in_camp and len(in_camp) == len(courses) and all(c.stream_id for c in in_camp):
            p.account_mode = "in_camp"
            p.save(update_fields=["account_mode"])
            for sid in {c.stream_id for c in in_camp}:
                st = Stream.objects.get(pk=sid)
                Membership.objects.get_or_create(
                    user_id=p.user_id, stream=st,
                    defaults={"role": "trainer", "status": "expired" if expired(st) else "active"})
        else:
            p.account_mode = "post_camp"
            p.save(update_fields=["account_mode"])


class Migration(migrations.Migration):
    dependencies = [("saed", "0007_streams_and_tracks")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
