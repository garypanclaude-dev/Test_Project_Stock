import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.database import SessionLocal

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="UTC")


def _run_tw_update():
    from app.services.collector import collect_market
    from app.services.predictor import predict_today
    db = SessionLocal()
    try:
        collect_market(db, "TW")
        predict_today(db)
    except Exception as e:
        logger.error(f"TW scheduled update failed: {e}")
    finally:
        db.close()


def _run_us_update():
    from app.services.collector import collect_market
    from app.services.predictor import predict_today
    db = SessionLocal()
    try:
        collect_market(db, "US")
        predict_today(db)
    except Exception as e:
        logger.error(f"US scheduled update failed: {e}")
    finally:
        db.close()


def _run_weekly_retrain():
    from app.services.predictor import train_model
    db = SessionLocal()
    try:
        train_model(db)
    except Exception as e:
        logger.error(f"Weekly retrain failed: {e}")
    finally:
        db.close()


def start_scheduler():
    # TW market close ~08:30 UTC (16:30 TST)
    scheduler.add_job(_run_tw_update, CronTrigger(hour=9, minute=0), id="tw_update", replace_existing=True)
    # US market close ~21:30 UTC
    scheduler.add_job(_run_us_update, CronTrigger(hour=22, minute=0), id="us_update", replace_existing=True)
    # Weekly retrain Sunday 01:00 UTC
    scheduler.add_job(_run_weekly_retrain, CronTrigger(day_of_week="sun", hour=1), id="weekly_retrain", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler():
    scheduler.shutdown(wait=False)
