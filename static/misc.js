let forms = document.querySelectorAll("form");
for (let form of forms) {
    form.addEventListener("submit", (event) => {
        // console.log(event)

        // Safari does not support this feature...
        // See: https://developer.mozilla.org/en-US/docs/Web/API/SubmitEvent/submitter
        // let btn = event.submitter;

        let btn = form.querySelectorAll("button[type='submit']")[0];
        btn.disabled = true;
        btn.classList.toggle("is-loading");
        btn.innerHTML = `加载中...`;
    })
}
