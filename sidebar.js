const prototypeMessage = "This is a Prototype and yet in development phase. These features will be enabled soon.";

document.querySelectorAll(".prototype-nav").forEach((item) => {
    item.addEventListener("click", () => {
        alert(prototypeMessage);
    });
});
