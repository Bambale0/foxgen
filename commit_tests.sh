cd /root/tanya/banano_kling && \
git add tests/test_rate_limiter.py tests/test_task_watchdog.py tests/test_lava_service.py tests/test_cryptobot_service.py tests/test_kie_market_service.py tests/test_video_reference_policy.py tests/test_yookassa_service.py && \
git commit -m "test: add 143 tests across 7 files — rate_limiter, task_watchdog, lava, cryptobot, kie_market, video_policy, yookassa" && \
git push origin tanyapi && \
echo "--- DONE ---"