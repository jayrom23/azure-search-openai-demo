import { Example } from "./Example";

import styles from "./Example.module.css";

export type ExampleModel = {
    text: string;
    value: string;
};

const EXAMPLES: ExampleModel[] = [
    {
        text: "Was ist der Inhalt und Zweck des Green Riders?",
        value: "Was ist der Inhalt und Zweck des Green Riders?"
    },
    { text: "Welche Massnahmen zur CO2-Reduktion könnten aus Sicht des Veranstalters umgesetzt werden?", value: "Welche Massnahmen zur CO2-Reduktion könnten aus Sicht des Veranstalters umgesetzt werden?" },
    { text: "Was sind die grössten Emissionstreiber an Festivals?", value: "Was sind die grössten Emissionstreiber an Festivals?" }
];

interface Props {
    onExampleClicked: (value: string) => void;
}

export const ExampleList = ({ onExampleClicked }: Props) => {
    return (
        <ul className={styles.examplesNavList}>
            {EXAMPLES.map((x, i) => (
                <li key={i}>
                    <Example text={x.text} value={x.value} onClick={onExampleClicked} />
                </li>
            ))}
        </ul>
    );
};
