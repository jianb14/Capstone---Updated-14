/**
 * Services page interactive widgets:
 *  1. AI Style Quiz        → POST /services/theme-quiz/
 *  2. Instant Price Estimator (client-side calculation)
 *  3. Date Availability    → GET  /services/check-availability/?date=YYYY-MM-DD
 *
 * Data for the estimator comes from the #services-widget-data JSON
 * rendered by the ServicesPageView via |json_script.
 */
(function () {
    "use strict";

    /* ── CSRF (same cookie-reading approach as the chat widget) ── */
    function getCookie(name) {
        var cookies = document.cookie ? document.cookie.split(";") : [];
        for (var i = 0; i < cookies.length; i++) {
            var cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === name + "=") {
                return decodeURIComponent(cookie.substring(name.length + 1));
            }
        }
        return null;
    }

    function formatPeso(value) {
        return "₱" + Number(value || 0).toLocaleString("en-PH", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    /* ═══════════════ 1. AI Style Quiz ═══════════════ */
    var quizForm = document.getElementById("quizForm");
    var quizResult = document.getElementById("quizResult");
    var quizSubmit = document.getElementById("quizSubmit");

    function showQuizMessage(message, isError, extraClass) {
        quizResult.hidden = false;
        quizResult.className = "quiz-result " + (isError ? "quiz-result-error " : "") + (extraClass || "");
        quizResult.textContent = message;
    }

    if (quizForm && quizResult) {
        quizForm.addEventListener("submit", function (event) {
            event.preventDefault();

            var eventType = document.getElementById("quizEventType");
            var vibe = document.getElementById("quizVibe");

            if (!eventType.value || !vibe.value) {
                showQuizMessage("Please choose both an event type and a vibe.", true);
                return;
            }

            var originalLabel = quizSubmit ? quizSubmit.innerHTML : "";
            if (quizSubmit) {
                quizSubmit.disabled = true;
                quizSubmit.innerHTML = "<span>Styling your theme…</span>";
            }

            showQuizMessage("Our AI stylist is crafting your theme…", false, "quiz-loading");

            fetch("/services/theme-quiz/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCookie("csrftoken"),
                },
                body: JSON.stringify({
                    event_type: eventType.value,
                    vibe: vibe.value,
                    budget: (document.getElementById("quizBudget") || {}).value || "",
                    colors: (document.getElementById("quizColors") || {}).value || "",
                }),
            })
                .then(function (response) {
                    return response.json().then(function (data) {
                        return { ok: response.ok, data: data };
                    });
                })
                .then(function (result) {
                    if (result.ok && result.data.success) {
                        quizResult.hidden = false;
                        quizResult.className = "quiz-result quiz-result-success";
                        quizResult.innerHTML =
                            '<div class="quiz-result-head"><i class="fa-solid fa-wand-magic-sparkles"></i> Your AI Theme Suggestion</div>' +
                            '<div class="quiz-result-body">' + result.data.response + "</div>" +
                            '<a href="/booking/" class="btn btn-primary btn-sm"><span>Book This Style</span></a>';
                    } else {
                        showQuizMessage(result.data.error || "Something went wrong. Please try again.", true);
                    }
                })
                .catch(function () {
                    showQuizMessage("Network error. Please check your connection and try again.", true);
                })
                .finally(function () {
                    if (quizSubmit) {
                        quizSubmit.disabled = false;
                        quizSubmit.innerHTML = originalLabel;
                    }
                });
        });
    }

    /* ═══════════════ 2. Instant Price Estimator ═══════════════ */
    var widgetDataEl = document.getElementById("services-widget-data");
    var estimatorPackage = document.getElementById("estimatorPackage");
    var estimatorAddons = document.getElementById("estimatorAddons");
    var estimatorTotal = document.getElementById("estimatorTotal");
    var estimatorSubtotal = document.getElementById("estimatorSubtotal");
    var estimatorServiceCharge = document.getElementById("estimatorServiceCharge");
    var estimatorGrand = document.getElementById("estimatorGrand");

    if (widgetDataEl && estimatorPackage && estimatorAddons) {
        var widgetData = JSON.parse(widgetDataEl.textContent || "{}");
        var packages = widgetData.packages || [];
        var addons = widgetData.addons || [];
        var globalServiceCharge = parseFloat(widgetData.serviceCharge || 0) || 0;

        function recalcEstimate() {
            var selectedPackage = null;
            var packageId = estimatorPackage.value;
            for (var i = 0; i < packages.length; i++) {
                if (String(packages[i].id) === String(packageId)) {
                    selectedPackage = packages[i];
                    break;
                }
            }

            var addonsTotal = 0;
            var checked = estimatorAddons.querySelectorAll("input[type=checkbox]:checked");
            for (var j = 0; j < checked.length; j++) {
                for (var k = 0; k < addons.length; k++) {
                    if (String(addons[k].id) === String(checked[j].value)) {
                        addonsTotal += parseFloat(addons[k].price || 0) || 0;
                        break;
                    }
                }
            }

            if (!selectedPackage && addonsTotal === 0) {
                estimatorTotal.hidden = true;
                return;
            }

            var packagePrice = selectedPackage ? parseFloat(selectedPackage.price || 0) || 0 : 0;
            var subtotal = packagePrice + addonsTotal;
            var grandTotal = subtotal + globalServiceCharge;

            estimatorSubtotal.textContent = formatPeso(subtotal);
            estimatorServiceCharge.textContent = formatPeso(globalServiceCharge);
            estimatorGrand.textContent = formatPeso(grandTotal);
            estimatorTotal.hidden = false;
        }

        estimatorPackage.addEventListener("change", recalcEstimate);
        estimatorAddons.addEventListener("change", recalcEstimate);
    }

    /* ═══════════════ 3. Date Availability Quick-Check ═══════════════ */
    var availabilityDate = document.getElementById("availabilityDate");
    var availabilityCheck = document.getElementById("availabilityCheck");
    var availabilityResult = document.getElementById("availabilityResult");

    if (availabilityDate) {
        var todayIso = new Date().toISOString().split("T")[0];
        availabilityDate.min = todayIso;
    }

    function showAvailabilityMessage(message, isError) {
        availabilityResult.hidden = false;
        availabilityResult.className = "availability-result " + (isError ? "availability-taken" : "");
        availabilityResult.textContent = message;
    }

    function renderAvailabilityResult(data) {
        availabilityResult.hidden = false;
        availabilityResult.className =
            "availability-result " + (data.available ? "availability-open" : "availability-taken");

        var html = '<div class="availability-status">' +
            (data.available ? "✅ " : "❌ ") + data.message + "</div>";

        if (!data.available && data.suggestions && data.suggestions.length) {
            html += '<div class="availability-suggestions">';
            for (var i = 0; i < data.suggestions.length; i++) {
                var dateObj = new Date(data.suggestions[i] + "T00:00:00");
                var label = dateObj.toLocaleDateString("en-US", {
                    weekday: "short", month: "short", day: "numeric",
                });
                html += '<button type="button" class="availability-chip" data-date="' +
                    data.suggestions[i] + '">' + label + "</button>";
            }
            html += "</div>";
        }

        html += '<a href="/booking/" class="btn btn-primary btn-sm availability-book"><span>Book Your Event Now</span></a>';
        availabilityResult.innerHTML = html;

        var chips = availabilityResult.querySelectorAll(".availability-chip");
        for (var c = 0; c < chips.length; c++) {
            chips[c].addEventListener("click", function () {
                availabilityDate.value = this.getAttribute("data-date");
                availabilityCheck.click();
            });
        }
    }

    if (availabilityCheck && availabilityResult) {
        availabilityCheck.addEventListener("click", function () {
            var value = availabilityDate ? availabilityDate.value : "";

            if (!value) {
                showAvailabilityMessage("Please pick a date first.", true);
                return;
            }

            var originalLabel = availabilityCheck.innerHTML;
            availabilityCheck.disabled = true;
            availabilityCheck.innerHTML = "<span>Checking…</span>";

            fetch("/services/check-availability/?date=" + encodeURIComponent(value))
                .then(function (response) {
                    return response.json().then(function (data) {
                        return { ok: response.ok, data: data };
                    });
                })
                .then(function (result) {
                    if (result.ok && result.data.success) {
                        renderAvailabilityResult(result.data);
                    } else {
                        showAvailabilityMessage(result.data.error || "Unable to check availability.", true);
                    }
                })
                .catch(function () {
                    showAvailabilityMessage("Network error. Please try again.", true);
                })
                .finally(function () {
                    availabilityCheck.disabled = false;
                    availabilityCheck.innerHTML = originalLabel;
                });
        });
    }
})();