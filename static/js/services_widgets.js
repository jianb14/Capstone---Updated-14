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

    /* ═══════════════ 0. Custom Select Dropdowns ═══════════════ */
    function closeAllCustomSelects() {
        var open = document.querySelectorAll(".tool-field .custom-select-container.open");
        for (var i = 0; i < open.length; i++) {
            open[i].classList.remove("open");
        }
    }

    function setupCustomSelect(container) {
        var trigger = container.querySelector(".custom-select-trigger");
        var triggerLabel = trigger ? trigger.querySelector("span") : null;
        var options = container.querySelectorAll(".custom-select-options li");
        var hiddenInput = container.querySelector("input[type=hidden]");
        if (!trigger || !hiddenInput) return;

        trigger.addEventListener("click", function (e) {
            e.stopPropagation();
            if (container.classList.contains("open")) {
                container.classList.remove("open");
            } else {
                closeAllCustomSelects();
                container.classList.add("open");
            }
        });

        trigger.addEventListener("keydown", function (e) {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                trigger.click();
            } else if (e.key === "Escape") {
                container.classList.remove("open");
            }
        });

        for (var i = 0; i < options.length; i++) {
            options[i].addEventListener("click", function (e) {
                e.stopPropagation();
                var value = this.getAttribute("data-value") || "";
                hiddenInput.value = value;
                if (triggerLabel) {
                    triggerLabel.textContent = this.textContent;
                    if (value) {
                        triggerLabel.classList.add("has-value");
                    } else {
                        triggerLabel.classList.remove("has-value");
                    }
                }
                container.classList.remove("open");
                hiddenInput.dispatchEvent(new Event("change", { bubbles: true }));
            });
        }
    }

    var customSelectContainers = document.querySelectorAll(".tool-field .custom-select-container");
    for (var cs = 0; cs < customSelectContainers.length; cs++) {
        setupCustomSelect(customSelectContainers[cs]);
    }

    document.addEventListener("click", closeAllCustomSelects);

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
                            '<div class="quiz-result-head"><i class="fa-regular fa-lightbulb"></i> Your AI Theme Suggestion</div>' +
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
    var estimatorAdditionals = document.getElementById("estimatorAdditionals");
    var estimatorTotal = document.getElementById("estimatorTotal");
    var estimatorSubtotal = document.getElementById("estimatorSubtotal");
    var estimatorServiceCharge = document.getElementById("estimatorServiceCharge");
    var estimatorGrand = document.getElementById("estimatorGrand");

    if (widgetDataEl && estimatorPackage && estimatorAddons) {
        var widgetData = JSON.parse(widgetDataEl.textContent || "{}");
        var packages = widgetData.packages || [];
        var addons = widgetData.addons || [];
        var additionals = widgetData.additionals || [];
        var globalServiceCharge = parseFloat(widgetData.serviceCharge || 0) || 0;

        function findItemById(list, id) {
            for (var i = 0; i < list.length; i++) {
                if (String(list[i].id) === String(id)) return list[i];
            }
            return null;
        }

        function getSelectedPackage() {
            return findItemById(packages, estimatorPackage.value);
        }

        function getSelectedAddon() {
            var checked = estimatorAddons.querySelector("input[name=estimatorAddon]:checked");
            return checked ? findItemById(addons, checked.value) : null;
        }

        function getSelectedAdditional() {
            if (!estimatorAdditionals) return null;
            var checked = estimatorAdditionals.querySelector("input[name=estimatorAdditional]:checked");
            return checked ? findItemById(additionals, checked.value) : null;
        }

        // Mirror the booking flow: with a package the add-on shows its
        // discounted price; without one it falls back to the solo price and
        // add-ons that have no solo price are locked until a package is chosen.
        function updateAddonStates() {
            var hasPackage = !!getSelectedPackage();
            var labels = estimatorAddons.querySelectorAll(".addon-check");
            for (var i = 0; i < labels.length; i++) {
                var el = labels[i];
                var addon = findItemById(addons, el.getAttribute("data-id"));
                if (!addon) continue;
                var labelEl = el.querySelector(".addon-label");
                var input = el.querySelector("input");
                var soloPrice = parseFloat(addon.solo_price);
                if (hasPackage) {
                    if (labelEl) labelEl.textContent = addon.name + " (+" + formatPeso(addon.price) + ")";
                    el.classList.remove("is-disabled");
                    input.disabled = false;
                } else if (!isNaN(soloPrice) && soloPrice > 0) {
                    if (labelEl) labelEl.textContent = addon.name + " (Solo " + formatPeso(soloPrice) + ")";
                    el.classList.remove("is-disabled");
                    input.disabled = false;
                } else {
                    if (labelEl) labelEl.textContent = addon.name + " (+" + formatPeso(addon.price) + " w/ package)";
                    el.classList.add("is-disabled");
                    input.disabled = true;
                    input.checked = false;
                }
            }
        }

        // Welcome stand items only become selectable once a package or a solo
        // add-on is chosen (same rule as the booking page).
        function updateAdditionalStates() {
            if (!estimatorAdditionals) return;
            var hasBase = !!getSelectedPackage() || !!getSelectedAddon();
            var labels = estimatorAdditionals.querySelectorAll(".addon-check");
            for (var i = 0; i < labels.length; i++) {
                var el = labels[i];
                var input = el.querySelector("input");
                if (hasBase) {
                    el.classList.remove("is-disabled");
                    input.disabled = false;
                } else {
                    el.classList.add("is-disabled");
                    input.disabled = true;
                    input.checked = false;
                }
            }
        }

        function recalcEstimate() {
            updateAddonStates();
            updateAdditionalStates();

            var pkg = getSelectedPackage();
            var addon = getSelectedAddon();
            var additional = getSelectedAdditional();

            var baseTotal = 0;
            if (pkg) {
                baseTotal = parseFloat(pkg.price || 0) || 0;
            } else if (addon) {
                baseTotal = parseFloat(addon.solo_price || 0) || 0;
            }

            var addonTotal = 0;
            if (pkg && addon) {
                addonTotal = parseFloat(addon.price || 0) || 0;
            }

            var additionalTotal = additional ? (parseFloat(additional.price || 0) || 0) : 0;

            var hasBaseSelection = !!pkg || !!addon;
            if (!hasBaseSelection) {
                estimatorTotal.hidden = true;
                return;
            }

            var subtotal = baseTotal + addonTotal + additionalTotal;
            var grandTotal = subtotal + globalServiceCharge;

            estimatorSubtotal.textContent = formatPeso(subtotal);
            estimatorServiceCharge.textContent = formatPeso(globalServiceCharge);
            estimatorGrand.textContent = formatPeso(grandTotal);
            estimatorTotal.hidden = false;
        }

        estimatorPackage.addEventListener("change", recalcEstimate);
        estimatorAddons.addEventListener("change", recalcEstimate);
        if (estimatorAdditionals) {
            estimatorAdditionals.addEventListener("change", recalcEstimate);
        }

        recalcEstimate();
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